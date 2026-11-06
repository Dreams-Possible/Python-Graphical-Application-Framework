"""翻译限长、缓存、失败回退与英文原文保留。"""
from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from src.features.translation.service import Translator as HistoryTranslator, chunks
from src.features.calendar.history import HistoryRepository, HistoryQuery


class TranslationTests(unittest.TestCase):
    def test_calendar_writes_only_two_daily_files_without_sentence_cache(self):
        with TemporaryDirectory() as directory:
            repo = HistoryRepository(Path(directory))
            query = HistoryQuery(11, 5, "en", "https://en.wikipedia.org/{month}/{day}", 5, target_language="zh")
            doc = {"selected": [{"year": 1900, "text": "First event"}, {"year": 2000, "text": "Second event"}]}
            with patch("src.features.calendar.history.get_json", return_value=doc) as source, patch(
                "src.features.translation.service.get_json", side_effect=lambda endpoint, parameters, *args, **kwargs:
                    {"responseStatus": 200, "responseData": {"translatedText": {"First event": "第一条", "Second event": "第二条"}[parameters['q']]}}) as translation:
                result = repo.fetch(query, Event())
                repo.save(result)
                repo.save(repo.fetch(query, Event()))
                self.assertEqual(source.call_count, 1)
                self.assertEqual(translation.call_count, 2)
            self.assertEqual(sorted(p.relative_to(repo.cache).as_posix() for p in repo.cache.rglob('*') if p.is_file()),
                             ['11-05/source.json', '11-05/translated.json'])
            original = json.loads((repo.cache / '11-05/source.json').read_text(encoding='utf-8'))
            translated = json.loads((repo.cache / '11-05/translated.json').read_text(encoding='utf-8'))
            self.assertEqual([item['text'] for item in original['events']], ['Second event', 'First event'])
            self.assertEqual(translated['translations'], {'0': '第二条', '1': '第一条'})
            self.assertEqual(set(translated), {'schema_version', 'key', 'source_hash', 'translations'})
            self.assertTrue(repo.read(query).complete)
            self.assertEqual(repo.read(query).events[0].year, 2000)
            self.assertEqual(repo.read(query).events[0].original_text, 'Second event')
            translated['translations']['99'] = '不存在的条目'
            (repo.cache / '11-05/translated.json').write_text(json.dumps(translated), encoding='utf-8')
            self.assertIsNone(repo.read(query))

    def test_partial_daily_result_retries_only_missing_and_limit_does_not_fork_files(self):
        with TemporaryDirectory() as directory:
            repo = HistoryRepository(Path(directory))
            query = HistoryQuery(2, 29, "en", "https://en.wikipedia.org/{month}/{day}", 5, target_language="zh", limit=2)
            doc = {"selected": [{"year": 1902 - i, "text": f"Event {i}"} for i in range(3)]}
            with patch("src.features.calendar.history.get_json", return_value=doc), patch.object(repo.translator, 'translate', side_effect=['译文0', ValueError('quota')]):
                partial = repo.fetch(query, Event())
                repo.save(partial)
            self.assertFalse(repo.read(query).complete)
            self.assertEqual([event.translation_status for event in partial.events], ['translated', 'failed', 'pending'])
            stored = json.loads(repo._path(query).read_text(encoding='utf-8'))
            self.assertEqual(stored['translations'], {'0': '译文0'})
            self.assertNotIn('Event ', repo._path(query).read_text(encoding='utf-8'))
            self.assertEqual([event.translation_status for event in repo.read(query).events], ['translated', 'pending', 'pending'])
            with patch("src.features.calendar.history.get_json") as source, patch.object(repo.translator, 'translate', side_effect=['译文1', '译文2']) as translate:
                expanded = replace(query, limit=3)
                complete = repo.fetch(expanded, Event())
                repo.save(complete)
                self.assertEqual([call.args[0] for call in translate.call_args_list], ['Event 1', 'Event 2'])
                self.assertTrue(all(call.kwargs['use_cache'] is False for call in translate.call_args_list))
                source.assert_not_called()
            self.assertTrue(repo.read(expanded).complete)
            self.assertEqual(len(list(repo.cache.rglob('*.json'))), 2)

    def test_changed_original_invalidates_daily_translation_and_equal_text_can_succeed(self):
        with TemporaryDirectory() as directory:
            repo = HistoryRepository(Path(directory))
            query = HistoryQuery(11, 5, 'en', 'https://en.wikipedia.org/{month}/{day}', 5, target_language='zh')
            with patch('src.features.calendar.history.get_json', return_value={'selected': [{'year': 1900, 'text': 'Name'}]}), patch.object(repo.translator, 'translate', return_value='Name'):
                repo.save(repo.fetch(query, Event()))
            self.assertTrue(repo.read(query).complete)
            with patch('src.features.calendar.history.get_json', return_value={'selected': [{'year': 1900, 'text': 'Changed'}]}), patch.object(repo.translator, 'translate', return_value='新译文') as translate:
                repo.save(repo.fetch(replace(query, refresh=True), Event()))
                self.assertEqual(translate.call_args.args[0], 'Changed')
            self.assertEqual(repo.read(query).events[0].text, '新译文')
            self.assertEqual(len(list(repo.cache.rglob('*.json'))), 2)

    def test_chunks_are_lossless_and_fit_provider_byte_limit(self):
        text = ("An important event happened on this day. " * 35) + "世界"
        parts = list(chunks(text))
        self.assertEqual("".join(parts), text)
        self.assertTrue(all(0 < len(part.encode()) <= 450 for part in parts))

    def test_translation_cache_avoids_duplicate_requests(self):
        with TemporaryDirectory() as directory:
            translator = HistoryTranslator(Path(directory))
            with patch("src.features.translation.service.get_json", return_value={"responseStatus": 200, "responseData": {"translatedText": "历史事件"}}) as request:
                self.assertEqual(translator.translate("A historical event", 5, Event()), "历史事件")
                self.assertEqual(translator.translate("A historical event", 5, Event()), "历史事件")
                self.assertEqual(request.call_count, 1)
                self.assertEqual(request.call_args.args[1]["langpair"], "en|zh-CN")

    def test_quota_response_is_not_cached_as_translation(self):
        with TemporaryDirectory() as directory:
            translator = HistoryTranslator(Path(directory))
            with patch("src.features.translation.service.get_json", return_value={"responseStatus": 429, "responseData": {"translatedText": "quota exceeded"}}):
                with self.assertRaises(ValueError):
                    translator.translate("English original", 5, Event())
            self.assertFalse(list(Path(directory).rglob("*.txt")))

    def test_repository_retains_original_and_shares_english_cache(self):
        with TemporaryDirectory() as directory:
            repository = HistoryRepository(Path(directory))
            query = HistoryQuery(11, 5, "en", "https://en.wikipedia.org/{month}/{day}", 5, target_language="zh")
            doc = {"selected": [{"year": 1969, "text": "English original"}]}
            with patch("src.features.calendar.history.get_json", return_value=doc) as request, patch.object(repository.translator, "translate", return_value="中文译文"):
                snapshot = repository.fetch(query, Event())
                repository.save(snapshot)
                self.assertEqual(repository.read(query).events[0].original_text, "English original")
                self.assertEqual(repository.read(query).events[0].text, "中文译文")
                english = repository.fetch(replace(query, target_language="en"), Event())
                self.assertEqual(english.events[0].text, "English original")
                self.assertEqual(request.call_count, 1)
                repository.fetch(replace(query, target_language="en", refresh=True), Event())
                self.assertEqual(request.call_count, 2)
            with patch.object(repository.translator, "translate", side_effect=ValueError("quota")):
                repository._path(query).unlink()
                failed = repository.fetch(query, Event())
                self.assertEqual(failed.events[0].text, "English original")
                self.assertEqual(failed.events[0].original_text, "English original")
