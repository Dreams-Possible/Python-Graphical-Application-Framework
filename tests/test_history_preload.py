"""预加载与前台共用缓存及在途任务，定时检查、取消和错误隔离。"""
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
import unittest
from unittest.mock import patch

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from src.features.calendar.history import HistoryEvent, HistoryQuery, HistoryRepository, HistoryService, HistorySnapshot, TASK_KEY
from src.shared.localization import Localization
from src.shared.tasks import TaskRunner


class Configuration(QObject):
    changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.values = dict(history_enabled=True, history_limit=10, history_preload=True,
                           history_preload_days=7, history_preload_minutes=60,
                           history_url='https://en.wikipedia.org/{month}/{day}', timeout_seconds=10)

    def get(self, key):
        return self.values.copy() if key == 'calendar' else {}


class Tasks(QObject):
    completed = Signal(str, int, object, object, bool)
    activity_changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.jobs, self.cancelled = {}, []
        self.sequence = 0

    def submit(self, key, work):
        if key in self.jobs:
            raise RuntimeError('finishing')
        self.sequence += 1
        self.jobs[key] = (self.sequence, work)
        return self.sequence

    def is_active(self, key):
        return key in self.jobs

    def cancel(self, key):
        self.cancelled.append(key)

    def finish(self, key, result=None, error='', cancelled=False):
        generation, _ = self.jobs[key]
        self.completed.emit(key, generation, result, error, cancelled)
        del self.jobs[key]
        self.activity_changed.emit(len(self.jobs))


class PreloadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.now, self.today = 1000000, date(2026, 12, 31)
        self.repo = HistoryRepository(Path(self.directory.name), now=lambda: self.now)
        self.tasks, self.configuration = Tasks(), Configuration()
        self.texts = Localization(mode='en-US')
        self.service = HistoryService(self.tasks, self.configuration, self.repo, self.texts)
        self.addCleanup(self.service.stop)

    def snapshot(self, query, reason=''):
        raw = HistoryEvent(2020, 'Original')
        if query.needs_translation:
            self.repo.save(HistorySnapshot(replace(query, target_language='en'), self.now, (raw,)))
            event = replace(raw, text='中文' if not reason else raw.text, original_text=raw.text,
                            translation_status='translated' if not reason else 'failed')
        else:
            event = raw
        return HistorySnapshot(query, self.now, (event,), reason)

    def start(self):
        self.service.start_preload(lambda: self.today)

    def drain(self):
        queries = []
        while self.service._background:
            key = next(iter(self.service._background))
            _, query = self.service._background[key]
            queries.append(query)
            self.assertLessEqual(len(self.service._background), 3)
            self.tasks.finish(key, self.snapshot(query))
        return queries

    def test_start_preloads_fifteen_dates_concurrently_and_timer_reuses_cache(self):
        self.start()
        self.assertEqual(len(self.service._background), 3)
        queries = self.drain()
        expected = {(day.month, day.day) for day in (self.today + timedelta(days=offset) for offset in range(-7, 8))}
        self.assertEqual({(query.month, query.day) for query in queries}, expected)
        self.assertEqual(len(queries), 15)
        self.assertEqual((queries[0].month, queries[0].day), (12, 31))
        self.assertTrue(self.service._preload_timer.isActive())
        self.assertEqual(self.service._preload_timer.interval(), 3600000)
        sequence = self.tasks.sequence
        self.service._preload_timer.timeout.emit()
        self.assertEqual(self.tasks.sequence, sequence)
        self.now += 86401
        self.service._preload_timer.timeout.emit()
        self.assertEqual(len(self.service._background), 3)

    def test_visible_page_attaches_to_existing_background_and_unrelated_results_do_not_replace_it(self):
        self.start()
        key = next(iter(self.service._background))
        _, query = self.service._background[key]
        self.service.load(self.today)
        self.assertNotIn(TASK_KEY, self.tasks.jobs)
        other = next(item for item in self.service._background if item != key)
        other_query = self.service._background[other][1]
        self.tasks.finish(other, self.snapshot(other_query))
        self.assertTrue(self.service.state.busy)
        self.tasks.finish(key, self.snapshot(query))
        self.assertEqual(self.service.state.key, query.key)
        self.assertFalse(self.service.state.busy)
        self.assertEqual(self.service.state.events[0].text, 'Original')

    def test_leaving_page_does_not_cancel_preload_and_cache_is_available_when_returning(self):
        self.start()
        key = next(iter(self.service._background))
        query = self.service._background[key][1]
        self.service.load(self.today)
        self.service.suspend()
        self.assertNotIn(key, self.tasks.cancelled)
        self.tasks.finish(key, self.snapshot(query))
        self.assertFalse(self.service._active)
        self.service.load(self.today)
        self.assertFalse(self.service.state.busy)
        self.assertEqual(self.service.state.status.key, 'calendar.history.cached')

    def test_foreground_missing_date_still_fetches_and_preloader_does_not_duplicate_it(self):
        self.service.load(self.today)
        query = self.service._current
        self.start()
        self.assertNotIn(query.key, [item.key for _, item in self.service._background.values()])
        self.tasks.finish(TASK_KEY, self.snapshot(query))
        self.assertEqual(self.service.state.key, query.key)
        self.assertFalse(self.service.state.busy)

    def test_disable_invalidates_background_results_but_frontend_still_works(self):
        self.start()
        key = next(iter(self.service._background))
        query = self.service._background[key][1]
        self.configuration.values['history_preload'] = False
        self.configuration.changed.emit('calendar')
        self.assertIn(key, self.tasks.cancelled)
        self.assertFalse(self.service._preload_timer.isActive())
        self.tasks.finish(key, self.snapshot(query))
        self.assertNotIn(query.key, self.service._memo)
        self.service.load(self.today)
        self.assertIn(TASK_KEY, self.tasks.jobs)

    def test_language_switch_discards_old_results_and_preloads_new_target(self):
        self.start()
        key = next(iter(self.service._background))
        query = self.service._background[key][1]
        self.texts.set_language('zh-CN')
        self.assertTrue(all(item.target_language == 'zh-CN' for _, item in self.service._background.values()))
        self.tasks.finish(key, self.snapshot(query))
        self.assertNotIn(query.key, self.service._memo)

    def test_quota_stops_round_without_retry_loop_and_next_tick_can_retry(self):
        self.texts.set_language('zh-CN')
        self.start()
        key = next(iter(self.service._background))
        query = self.service._background[key][1]
        self.service.load(self.today)
        self.tasks.finish(key, self.snapshot(query, 'quota'))
        self.assertEqual(self.service.state.status.key, 'calendar.history.translation_quota')
        self.assertTrue(self.service._preload_blocked)
        self.assertFalse(self.service._preload_queue)
        for key in list(self.service._background):
            self.tasks.finish(key, error='cancelled', cancelled=True)
        self.assertFalse(self.tasks.jobs)
        self.service._preload_timer.timeout.emit()
        self.assertTrue(self.service._background)

    def test_timer_uses_current_local_date_and_stop_prevents_new_tasks(self):
        self.start()
        self.drain()
        self.today += timedelta(days=1)
        self.service._preload_timer.timeout.emit()
        self.assertEqual(len(self.service._background), 1)
        query = next(iter(self.service._background.values()))[1]
        self.assertEqual((query.month, query.day), (1, 8))
        self.service.stop()
        sequence = self.tasks.sequence
        self.service.preload()
        self.tasks.activity_changed.emit(0)
        self.assertEqual(self.tasks.sequence, sequence)

    def test_periodic_refresh_updates_current_visible_cached_day(self):
        self.start()
        self.drain()
        self.service.load(self.today)
        self.now += 86401
        self.service._preload_timer.timeout.emit()
        key = next(key for key, (_, query) in self.service._background.items()
                   if (query.month, query.day) == (self.today.month, self.today.day))
        query = self.service._background[key][1]
        result = replace(self.snapshot(query), events=(HistoryEvent(2024, 'Updated'),))
        self.tasks.finish(key, result)
        self.assertEqual(self.service.state.events[0].text, 'Updated')

    def test_real_background_tasks_share_frontend_request_and_complete_cleanly(self):
        from PySide6.QtTest import QTest
        self.configuration.values['history_preload_days'] = 1
        tasks = TaskRunner()
        service = HistoryService(tasks, self.configuration, self.repo, self.texts)
        try:
            with patch.object(self.repo, 'fetch', side_effect=lambda query, stop, **kwargs: self.snapshot(query)) as fetch:
                service.start_preload(lambda: self.today)
                service.load(self.today)
                self.assertFalse(tasks.is_active(TASK_KEY))
                deadline = monotonic() + 3
                while tasks.active_count and monotonic() < deadline:
                    QTest.qWait(10)
                self.assertEqual(tasks.active_count, 0)
                self.assertEqual(fetch.call_count, 3)
                self.assertFalse(service.state.busy)
                self.assertEqual(service.state.events[0].text, 'Original')
                self.assertEqual(len(list(self.repo.cache.rglob('source.json'))), 3)
        finally:
            service.stop()
            tasks.shutdown()
            deadline = monotonic() + 3
            while tasks.active_count and monotonic() < deadline:
                QTest.qWait(10)
