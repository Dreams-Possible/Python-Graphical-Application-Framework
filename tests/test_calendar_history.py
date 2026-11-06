"""历史事件查询、缓存、过期结果丢弃与日视图按需加载。"""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal, QDate
from PySide6.QtWidgets import QApplication, QLabel
from src.features.calendar.history import (HistoryEvent, HistoryQuery, HistoryRepository,
    HistoryService, HistorySnapshot, TASK_KEY, parse_events, safe_article)
from src.features.calendar.view import CalendarView
from src.shared.localization import Localization
from src.shared.theme import ThemeManager


class Configuration(QObject):
    changed = Signal(str)
    def __init__(self):
        super().__init__()
        self.values = dict(history_enabled=True, history_language="zh", history_limit=10,
            history_url="https://{language}.wikipedia.org/api/rest_v1/feed/onthisday/events/{month}/{day}", timeout_seconds=10)
    def get(self, key):
        return self.values.copy()


class Tasks(QObject):
    completed = Signal(str, int, object, object, bool)
    activity_changed = Signal(int)
    def __init__(self):
        super().__init__()
        self.jobs = {}
        self.sequence = 0
    def submit(self, key, fn):
        if key in self.jobs:
            raise RuntimeError("busy")
        self.sequence += 1
        self.jobs[key] = (self.sequence, fn)
        return self.sequence
    def cancel(self, key):
        pass
    def is_active(self, key):
        return key in self.jobs
    def finish(self, result=None, error="", cancelled=False):
        generation, _ = self.jobs[TASK_KEY]
        self.completed.emit(TASK_KEY, generation, result, error, cancelled)
        del self.jobs[TASK_KEY]
        self.activity_changed.emit(0)


class HistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now = 1000000
        self.repository = HistoryRepository(Path(self.directory.name), now=lambda: self.now)
        self.tasks, self.configuration = Tasks(), Configuration()
        self.texts = Localization(mode="en-US")
        self.service = HistoryService(self.tasks, self.configuration, self.repository, self.texts)

    def snapshot(self, query):
        return HistorySnapshot(query, self.now, (HistoryEvent(2024, "Event text", "https://en.wikipedia.org/wiki/Example"),))

    def test_parser_preserves_text_orders_years_and_only_accepts_source_links(self):
        doc = {"events": [
            {"year": 1900, "text": "  An event  ", "pages": [{"content_urls": {"desktop": {"page": "javascript:alert(1)"}}}]},
            {"year": 2024, "text": "Recent event", "pages": [{"content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Example"}}}]},
            {"year": -44, "text": "An ancient event"}, {"year": 1900, "text": "An event"}]}
        events = parse_events(doc)
        self.assertEqual([event.year for event in events], [2024, 1900, -44])
        self.assertEqual(events[1].article, "")
        self.assertEqual(events[0].article, "https://en.wikipedia.org/wiki/Example")
        self.assertEqual(safe_article("https://en.wikipedia.org.evil.test/"), "")
        for invalid in ({}, {"events": [{"year": True, "text": "bad"}]}, {"events": [{"year": 1900}]}):
            with self.assertRaises(ValueError):
                parse_events(invalid)

    def test_selected_response_wins_and_empty_selection_does_not_fall_back(self):
        events = parse_events({"selected": [{"year": 1969, "text": "Selected milestone"}], "events": [{"year": 2024, "text": "Bulk event"}]})
        self.assertEqual([event.text for event in events], ["Selected milestone"])
        self.assertEqual(parse_events({"selected": [], "events": [{"year": 2024, "text": "Bulk"}]}), ())

    def test_default_calendar_migration_preserves_custom_sources(self):
        import json
        from src.features.calendar.settings import migrate_calendar_settings
        from src.features.calendar.settings import SECTION
        from src.shared.configuration import SettingsRegistry, SettingsRepository
        old = "https://{language}.wikipedia.org/api/rest_v1/feed/onthisday/events/{month}/{day}"
        values = migrate_calendar_settings(1, {"history_url": old, "history_limit": 20})
        self.assertIn("/selected/", values["history_url"])
        self.assertEqual(values["history_limit"], 10)
        registry = SettingsRegistry()
        registry.register(SECTION)
        config_path = Path(self.directory.name) / "calendar.json"
        config_path.write_text(json.dumps({"schema_version": 1, "values": {"history_url": old, "history_limit": 20}}), encoding="utf-8")
        saved = SettingsRepository(Path(self.directory.name), registry).load("calendar")
        self.assertIn("/selected/", saved["history_url"])
        self.assertEqual(saved["history_limit"], 10)
        self.assertEqual(json.loads(config_path.read_text(encoding="utf-8"))["schema_version"], 3)
        self.assertEqual(migrate_calendar_settings(2, {"history_limit": 5})["history_limit"], 10)
        self.assertEqual(migrate_calendar_settings(2, {"history_limit": 8})["history_limit"], 8)
        custom = {"history_url": "https://example.test/{month}/{day}", "history_limit": 8}
        self.assertEqual(migrate_calendar_settings(1, custom.copy()), custom)

    def test_anniversaries_update_with_selected_year_and_metadata_is_at_bottom(self):
        from src.features.calendar.history_view import HistoryEventsView
        texts = Localization(mode="zh-CN")
        self.service.load(date(2026, 11, 5))
        query = self.service._current
        self.tasks.finish(HistorySnapshot(query, self.now, (HistoryEvent(1969, "A milestone"),)))
        view = HistoryEventsView(texts, self.service)
        view.set_day(QDate(2026, 11, 5))
        self.assertEqual(view._anniversaries[0][0].text(), "57 周年")
        view.set_day(QDate(2027, 11, 5))
        self.assertEqual(view._anniversaries[0][0].text(), "58 周年")
        self.assertIs(view.layout().itemAt(view.layout().count() - 1).widget(), view.metadata)
        self.assertIn("1 / 1", view.metadata.toolTip())
        view.close()

    def test_fresh_cache_is_keyed_by_month_day_language_and_source(self):
        query = HistoryQuery(11, 5, "en", self.configuration.values["history_url"], 10)
        self.repository.save(self.snapshot(query))
        self.service.load(date(2026, 11, 5))
        self.assertFalse(self.tasks.jobs)
        self.assertEqual(len(self.service.state.events), 1)
        self.service.load(date(1900, 11, 5))
        self.assertFalse(self.tasks.jobs)
        other = HistoryQuery(11, 5, "zh", query.template, 10)
        self.assertIsNone(self.repository.read(other))
        other = HistoryQuery(11, 5, "en", "https://example.test/{month}/{day}", 10)
        self.assertIsNone(self.repository.read(other))

    def test_fast_date_switch_only_displays_latest_request(self):
        self.service.load(date(2026, 11, 5))
        old_query = self.service._current
        self.service.load(date(2026, 11, 6))
        self.service.load(date(2026, 11, 7))
        self.tasks.finish(self.snapshot(old_query))
        self.assertEqual(self.service._current.day, 7)
        self.assertTrue(self.tasks.jobs)
        self.assertEqual(self.service.state.events, ())
        self.tasks.finish(self.snapshot(self.service._current))
        self.assertEqual(len(self.service.state.events), 1)
        self.assertFalse(self.service.state.busy)

    def test_partial_translation_cache_is_retried_even_when_source_is_fresh(self):
        from dataclasses import replace
        self.texts.set_language('zh-CN')
        query = HistoryQuery(11, 5, 'en', self.configuration.values['history_url'], 10, target_language='zh')
        self.repository.save(self.snapshot(replace(query, target_language='en')))
        failed = HistorySnapshot(query, self.now, (HistoryEvent(2024, 'Event text',
            'https://en.wikipedia.org/wiki/Example', 'Event text', 'failed'),))
        self.repository.save(failed)
        self.service.load(date(2026, 11, 5))
        self.assertTrue(self.tasks.jobs)
        complete = replace(failed, events=(replace(failed.events[0], text='译文', translation_status='translated'),))
        self.tasks.finish(complete)
        self.service.load(date(2026, 11, 5))
        self.assertFalse(self.tasks.jobs)
        self.assertEqual(self.service.state.events[0].text, '译文')

    def test_switch_to_cached_day_ignores_error_from_previous_request(self):
        query = HistoryQuery(11, 6, "en", self.configuration.values["history_url"], 10)
        self.repository.save(self.snapshot(query))
        self.service.load(date(2026, 11, 5))
        self.service.load(date(2026, 11, 6))
        self.tasks.finish(error="old error")
        self.assertEqual(self.service.state.key, query.key)
        self.assertEqual(self.service.state.status.key, "calendar.history.cached")

    def test_expired_cache_survives_failed_refresh_and_suspend_blocks_result(self):
        query = HistoryQuery(11, 5, "en", self.configuration.values["history_url"], 10)
        self.repository.save(self.snapshot(query))
        self.now += 2 * 86400
        self.service.load(date(2026, 11, 5))
        self.assertTrue(self.service.state.busy)
        self.tasks.finish(error="network down")
        self.assertEqual(self.service.state.status.key, "calendar.history.failed_cached")
        self.assertEqual(len(self.service.state.events), 1)
        self.service.load(date(2026, 11, 6))
        result = self.snapshot(self.service._current)
        self.service.suspend()
        self.tasks.finish(result)
        self.assertFalse(self.service.state.busy)
        self.assertEqual(self.service.state.status.key, "calendar.history.idle")
        self.assertEqual(self.service.state.events, ())
        self.assertNotIn(result.query.key, self.service._memo)

    def test_day_view_follows_software_language_and_source_is_always_english(self):
        texts = self.texts
        themes = ThemeManager(self.app)
        view = CalendarView(themes, texts, history=self.service)
        view.resize(900, 700)
        view.show()
        self.app.processEvents()
        self.assertFalse(self.tasks.jobs)
        view.set_mode("day")
        self.assertTrue(self.tasks.jobs)
        self.tasks.finish(self.snapshot(self.service._current))
        sequence = self.tasks.sequence
        texts.set_language("zh-CN")
        self.assertEqual(self.tasks.sequence, sequence + 1)
        self.assertEqual(self.service._current.language, "en")
        self.assertEqual(self.service._current.target_language, "zh-CN")
        self.tasks.finish(self.snapshot(self.service._current))
        self.assertIn("Event text", [label.text() for label in view.history_view.findChildren(QLabel)])
        view.set_mode("year")
        self.assertFalse(self.tasks.jobs)
        view.close()

    def test_repository_uses_descriptive_agent_and_zero_padded_date(self):
        query = HistoryQuery(2, 9, "zh", self.configuration.values["history_url"], 10)
        with patch("src.features.calendar.history.get_json", return_value={"events": []}) as request:
            self.repository.fetch(query, Event())
        self.assertTrue(request.call_args.args[0].endswith("/02/09"))
        self.assertIn("Daylight/", request.call_args.kwargs["user_agent"])

    def test_day_preview_does_not_request_until_date_is_committed(self):
        from PySide6.QtTest import QTest
        from src.shared.ui_metrics import UI
        texts = Localization(mode="zh-CN")
        view = CalendarView(ThemeManager(self.app), texts, history=self.service)
        view.date = view.shown = QDate(2026, 11, 5)
        view.resize(900, 700)
        view.show()
        view.set_mode("day")
        self.app.processEvents()
        self.tasks.finish(self.snapshot(self.service._current))
        sequence = self.tasks.sequence
        QTest.qWait(100)
        try:
            view.day_pages.begin_swipe()
            view.day_pages.move_swipe(-100)
            self.assertEqual(self.tasks.sequence, sequence)
            self.assertEqual(view.date, QDate(2026, 11, 5))
            self.assertIsNone(view.day_pages.pages[0].history_view)
            self.assertIsNone(view.day_pages.pages[2].history_view)
            view.day_pages.end_swipe(-240, 0)
            QTest.qWait(UI.page_slide_ms + 30)
            self.assertEqual(view.date, QDate(2026, 11, 6))
            self.assertEqual(self.tasks.sequence, sequence + 1)
            self.assertEqual(self.service._current.day, 6)
        finally:
            view.close()
