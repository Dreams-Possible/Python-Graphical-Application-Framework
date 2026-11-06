"""翻译限长、缓存、失败回退与英文原文保留。"""
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch
from src.features.translation.service import Translator as HistoryTranslator, chunks
from src.features.calendar.history import HistoryRepository, HistoryQuery


class TranslationTests(unittest.TestCase):
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
                failed = repository.fetch(query, Event())
                self.assertEqual(failed.events[0].text, "English original")
                self.assertEqual(failed.events[0].original_text, "English original")
