"""集合翻译的原生批量、并发上限、顺序、限流与取消。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Lock, Barrier
from urllib.error import HTTPError
import unittest
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from src.features.translation import Translator, TranslationOptions
from src.shared.tasks import TaskCancelled


class ManyTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.translator = Translator(Path(self.directory.name))

    def test_multiple_date_batches_share_one_global_concurrency_limit(self):
        from src.features.translation.service import _REQUEST_LIMITER
        lock, barrier = Lock(), Barrier(2)
        active, maximum = 0, 0
        def translate(text, *args, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                barrier.wait(timeout=3)
                return 'T:' + text
            finally:
                with lock:
                    active -= 1
        def batch():
            return self.translator.translate_many(['a', 'b', 'c', 'd'], 5, Event(), use_cache=False, max_workers=2)
        with patch.object(self.translator, 'translate', side_effect=translate), ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(batch) for _ in range(2)]
            self.assertTrue(all(result.succeeded for future in futures for result in future.result(timeout=8)))
        self.assertEqual(maximum, 2)
        self.assertEqual(_REQUEST_LIMITER.active, 0)

    def test_setting_controls_concurrency_and_does_not_invalidate_translation_cache(self):
        from dataclasses import replace
        options = TranslationOptions.from_values({'max_workers': 3})
        self.assertEqual(TranslationOptions.from_values({}).max_workers, 10)
        self.assertEqual(options.signature, replace(options, max_workers=10).signature)
        barrier, lock = Barrier(3), Lock()
        active, maximum = 0, 0
        def translate(text, *args, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                if int(text) < 3:
                    barrier.wait(timeout=3)
                return 'T:' + text
            finally:
                with lock:
                    active -= 1
        with patch.object(self.translator, 'translate', side_effect=translate):
            results = self.translator.translate_many(['0', '1', '2', '3'], 5, Event(), options, use_cache=False)
        self.assertTrue(all(result.succeeded for result in results))
        self.assertEqual(maximum, 3)
        for count in (0, 11, True):
            with self.assertRaises(ValueError):
                self.translator.translate_many(['text'], 5, Event(), max_workers=count)

    def test_fallback_overlaps_two_requests_and_restores_input_order(self):
        lock, overlap = Lock(), Event()
        active, maximum = 0, 0
        def translate(text, *args, **kwargs):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
                if active == 2:
                    overlap.set()
            try:
                self.assertTrue(overlap.wait(3), 'requests did not overlap')
                return 'translated ' + text
            finally:
                with lock:
                    active -= 1
        with patch.object(self.translator, 'translate', side_effect=translate):
            results = self.translator.translate_many(['first', 'second', 'third', 'fourth'], 5, Event(), use_cache=False, max_workers=2)
        self.assertEqual([result.text for result in results], ['translated ' + text for text in ['first', 'second', 'third', 'fourth']])
        self.assertEqual(maximum, 2)

    def test_google_batches_arrays_and_reuses_successful_item_cache(self):
        options = TranslationOptions.from_values({'provider': 'google', 'google_key': 'key'})
        texts = [f'Event {index}' for index in range(80)]
        def respond(endpoint, payload, *args, **kwargs):
            self.assertIsInstance(payload['q'], list)
            self.assertLessEqual(len(payload['q']), 32)
            return {'data': {'translations': [{'translatedText': 'T:' + text} for text in payload['q']]}}
        with patch('src.features.translation.service.post_json', side_effect=respond) as request:
            results = self.translator.translate_many(texts, 5, Event(), options)
            self.assertEqual(request.call_count, 3)
            self.assertEqual([result.text for result in results], ['T:' + text for text in texts])
            again = self.translator.translate_many(texts, 5, Event(), options)
            self.assertEqual(request.call_count, 3)
            self.assertEqual(again, results)

    def test_libre_long_items_are_split_and_reassembled(self):
        options = TranslationOptions.from_values({'provider': 'libre'})
        text = 'long historical event ' * 80
        def respond(endpoint, payload, *args, **kwargs):
            self.assertTrue(all(len(part.encode()) <= 450 for part in payload['q']))
            return {'translatedText': ['T' for _ in payload['q']]}
        with patch('src.features.translation.service.post_json', side_effect=respond):
            results = self.translator.translate_many([text, 'short'], 5, Event(), options, use_cache=False)
        self.assertTrue(results[0].succeeded)
        self.assertGreater(len(results[0].text.split()), 1)
        self.assertEqual(results[1].text, 'T')

    def test_rate_limit_stops_dispatch_and_does_not_cache_failures(self):
        options = TranslationOptions.from_values({'provider': 'google', 'google_key': 'key'})
        with patch('src.features.translation.service.post_json', side_effect=HTTPError('https://example.org', 429, 'rate', {}, None)) as request:
            results = self.translator.translate_many([str(index) for index in range(70)], 5, Event(), options, max_workers=1)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(results[0].error.reason, 'quota')
        self.assertTrue(results[-1].skipped)
        self.assertFalse(list(Path(self.directory.name).rglob('*.txt')))

    def test_bad_array_count_marks_group_failed_without_cache(self):
        options = TranslationOptions.from_values({'provider': 'libre'})
        with patch('src.features.translation.service.post_json', return_value={'translatedText': ['only one']}):
            results = self.translator.translate_many(['one', 'two'], 5, Event(), options)
        self.assertTrue(all(result.error.reason == 'invalid_response' for result in results))
        self.assertFalse(list(Path(self.directory.name).rglob('*.txt')))

    def test_cancellation_does_not_dispatch_rest_or_save_partial_cache(self):
        stop = Event()
        def cancel(*args, **kwargs):
            stop.set()
            return 'partial'
        with patch.object(self.translator, 'translate', side_effect=cancel) as request:
            with self.assertRaises(TaskCancelled):
                self.translator.translate_many(['one', 'two', 'three'], 5, stop, max_workers=1)
        self.assertEqual(request.call_count, 1)
        self.assertFalse(list(Path(self.directory.name).rglob('*.txt')))

    def test_one_failure_keeps_other_successes_and_noop_skips_network(self):
        def translate(text, *args, **kwargs):
            if text == 'bad':
                raise TimeoutError()
            return 'T:' + text
        with patch.object(self.translator, 'translate', side_effect=translate):
            results = self.translator.translate_many(['one', 'bad', 'three', ''], 5, Event(), use_cache=False)
        self.assertEqual([results[0].text, results[2].text, results[3].text], ['T:one', 'T:three', ''])
        self.assertIsNotNone(results[1].error)
        with patch.object(self.translator, 'translate') as request:
            results = self.translator.translate_many(['one', 'two'], 5, Event(), source_language='en', target_language='en')
            request.assert_not_called()
            self.assertEqual([result.text for result in results], ['one', 'two'])
