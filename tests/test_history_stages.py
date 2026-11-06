"""英文先落盘与显示，译文增量替换，失败后只补翻译；统一语言回退。"""
from datetime import date
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
import json
import unittest
from unittest.mock import patch

from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtTest import QTest
from src.features.calendar.history import HistoryRepository, HistoryService, HistoryQuery, HistorySnapshot, HistoryEvent
from src.features.translation import TranslationResult
from src.features.calendar.history_view import HistoryEventsView
from src.features.translation import TranslationError
from src.features.translation.service import preferred_target_language
from src.shared.localization import Localization
from src.shared.tasks import TaskRunner, check_cancelled
from test_history_preload import Configuration


class StageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def wait_until(self, predicate):
        deadline = monotonic() + 4
        while not predicate() and monotonic() < deadline:
            QTest.qWait(10)
        self.assertTrue(predicate())

    def test_source_is_visible_and_cached_before_translation_and_retry_only_translates_missing(self):
        with TemporaryDirectory() as directory:
            repo = HistoryRepository(Path(directory))
            tasks = TaskRunner()
            texts = Localization(mode='zh-CN')
            service = HistoryService(tasks, Configuration(), repo, texts)
            view = HistoryEventsView(texts, service)
            first, second = Event(), Event()
            attempts = []
            def translate(text, timeout, stop, *args, **kwargs):
                attempts.append(text)
                release = first if text == 'English first' else second
                while not release.wait(0.02):
                    check_cancelled(stop)
                if text == 'English second' and attempts.count(text) == 1:
                    raise TranslationError('quota')
                return '中文一' if text == 'English first' else '中文二'
            document = {'selected': [{'year': 2024, 'text': 'English first'}, {'year': 2023, 'text': 'English second'}]}
            try:
                with patch('src.features.calendar.history.get_json', return_value=document) as source, patch.object(repo.translator, 'translate', side_effect=translate):
                    service.load(date(2026, 11, 6))
                    self.wait_until(lambda: len(service.state.events) == 2)
                    self.assertEqual([event.text for event in service.state.events], ['English first', 'English second'])
                    self.assertTrue(service.state.busy)
                    self.assertEqual(service.state.status.key, 'calendar.history.translating')
                    self.assertTrue((repo.cache / '11-06/source.json').exists())
                    self.assertIn('English first', [label.text() for label in view.findChildren(QLabel)])
                    first.set()
                    self.wait_until(lambda: service.state.events[0].text == '中文一')
                    self.assertEqual(service.state.events[1].text, 'English second')
                    self.assertTrue(service.state.busy)
                    second.set()
                    self.wait_until(lambda: tasks.active_count == 0)
                    self.assertFalse(service.state.busy)
                    self.assertEqual(service.state.status.key, 'calendar.history.translation_quota')
                    self.assertEqual(json.loads((repo.cache / '11-06/translated.zh-CN.json').read_text(encoding='utf-8'))['translations'], {'0': '中文一'})
                    self.assertEqual(source.call_count, 1)
                    service.load(date(2026, 11, 6))
                    self.wait_until(lambda: tasks.active_count == 0)
                    self.assertEqual([event.text for event in service.state.events], ['中文一', '中文二'])
                    self.assertEqual(source.call_count, 1)
                    self.assertEqual(attempts.count('English first'), 1)
                    self.assertEqual(attempts.count('English second'), 2)
            finally:
                first.set()
                second.set()
                service.stop()
                tasks.shutdown()
                self.wait_until(lambda: tasks.active_count == 0)
                view.close()
                view.deleteLater()

    def test_english_never_translates_and_future_supported_target_uses_its_own_language(self):
        with TemporaryDirectory() as directory:
            repo = HistoryRepository(Path(directory))
            english = HistoryQuery(11, 6, 'en', 'https://en.wikipedia.org/{month}/{day}', 5)
            with patch('src.features.calendar.history.get_json', return_value={'selected': [{'year': 2024, 'text': 'Original'}]}) as source, patch.object(repo.translator, 'translate_many') as translate:
                repo.fetch(english, Event())
                translate.assert_not_called()
                translate.return_value = ()
                french = HistoryQuery(11, 6, 'en', english.template, 5, target_language='fr')
                repo.fetch(french, Event())
                self.assertEqual(translate.call_args.kwargs['target_language'], 'fr')
                self.assertEqual(source.call_count, 1)
        self.assertEqual(preferred_target_language('fr-FR', 'mymemory'), 'fr')
        self.assertEqual(preferred_target_language('en-GB', 'mymemory'), 'en')
        self.assertEqual(preferred_target_language('zh-CN', 'mymemory'), 'zh-CN')
        self.assertEqual(preferred_target_language('fi-FI', 'mymemory'), 'en')

    def test_original_survives_translation_exception_and_existing_source_only_retries_translation(self):
        with TemporaryDirectory() as directory:
            repo = HistoryRepository(Path(directory), now=lambda: 1000000)
            query = HistoryQuery(11, 6, 'en', 'https://en.wikipedia.org/{month}/{day}', 5, target_language='zh-CN')
            source_query = replace(query, target_language='en')
            # 即使原文较旧，缺失译文时先单独补译，不重复拉取已有原文。
            repo.save(HistorySnapshot(source_query, 1, (HistoryEvent(2024, 'Original'),)))
            with patch('src.features.calendar.history.get_json') as source, patch.object(repo.translator, 'translate_many', side_effect=RuntimeError('translation failed')):
                with self.assertRaises(RuntimeError):
                    repo.fetch(query, Event())
                source.assert_not_called()
            self.assertEqual(repo.read(source_query).events[0].text, 'Original')
            with patch('src.features.calendar.history.get_json') as source, patch.object(repo.translator, 'translate_many', return_value=(TranslationResult('译文'),)):
                result = repo.fetch(query, Event())
                self.assertEqual(result.events[0].text, '译文')
                source.assert_not_called()

    def test_new_locale_prefers_its_own_resources_then_english(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for language, values in [('en-US', {'greeting': 'Hello', 'fallback': 'English'}),
                                     ('zh-CN', {'greeting': '你好'}), ('fr-FR', {'greeting': 'Bonjour'})]:
                (root / language).mkdir()
                (root / language / 'common.json').write_text(json.dumps(values), encoding='utf-8')
            texts = Localization(root, mode='system', system_languages=['fr-FR', 'zh-CN'])
            self.assertEqual(texts.language, 'fr-FR')
            self.assertEqual(texts.get('greeting'), 'Bonjour')
            self.assertEqual(texts.get('fallback'), 'English')
            texts.set_language('zh-CN')
            self.assertEqual(texts.get('fallback'), 'English')
