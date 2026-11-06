"""正式翻译 API 请求协议、签名、缓存隔离和错误脱敏。"""
from hashlib import md5, sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import traceback
from urllib.error import HTTPError
import unittest
from unittest.mock import patch
from src.features.translation import TranslationError, TranslationOptions, Translator, supported_languages
from src.features.translation.service import request_translation
from src.shared.tasks import TaskCancelled


class ProviderTests(unittest.TestCase):
    def options(self, provider, **changes):
        return TranslationOptions.from_values(dict(provider=provider, **changes))

    def test_language_mapping_for_every_provider(self):
        for provider, expected in (("google", ("ja", "zh-TW")), ("baidu", ("jp", "cht")),
                                   ("youdao", ("ja", "zh-CHT")), ("libre", ("ja", "zt"))):
            options = self.options(provider, **{provider + "_key": "key", provider + "_app_id": "app", provider + "_secret": "secret"})
            document = {"google": {"data": {"translations": [{"translatedText": "result"}]}},
                        "baidu": {"trans_result": [{"dst": "result"}]},
                        "youdao": {"errorCode": "0", "translation": ["result"]},
                        "libre": {"translatedText": "result"}}[provider]
            with self.subTest(provider=provider), patch("src.features.translation.service.post_json", return_value=document) as request:
                request_translation("text", options, Event(), source_language="ja-JP", target_language="zh-Hant")
                payload = request.call_args.args[1]
                self.assertEqual((payload.get("source", payload.get("from")), payload.get("target", payload.get("to"))), expected)
                if provider == "youdao":
                    self.assertEqual(payload["strict"], "true")
        with patch("src.features.translation.service.get_json", return_value={"responseStatus": 200, "responseData": {"translatedText": "result"}}) as request:
            request_translation("text", self.options("mymemory"), Event(), source_language="fr", target_language="en-US")
            self.assertEqual(request.call_args.args[1]["langpair"], "fr|en")

    def test_invalid_languages_fail_before_network_and_noop_needs_no_key(self):
        with TemporaryDirectory() as directory, patch("src.features.translation.service.post_json") as request:
            translator = Translator(Path(directory))
            options = self.options("google")
            for language in ("xx", "auto", "zh-unknown", None):
                with self.assertRaises(TranslationError) as caught:
                    translator.translate("text", 10, Event(), options, target_language=language)
                self.assertEqual(caught.exception.reason, "unsupported_language")
            self.assertEqual(translator.translate("text", 10, Event(), options, source_language="en-US", target_language="en"), "text")
            self.assertEqual(translator.translate("  ", 10, Event(), options), "  ")
            request.assert_not_called()
            self.assertIn("zh-TW", supported_languages("libre"))

    def test_language_pairs_have_separate_cache_and_aliases_share_cache(self):
        with TemporaryDirectory() as directory, patch("src.features.translation.service.get_json", return_value={"responseStatus": 200, "responseData": {"translatedText": "translated"}}) as request:
            translator = Translator(Path(directory))
            for source, target in (("en", "fr"), ("en-US", "fr-FR"), ("en", "de"), ("fr", "en")):
                translator.translate("text", 10, Event(), source_language=source, target_language=target)
            self.assertEqual(request.call_count, 3)

    def test_failures_are_classified_and_not_cached(self):
        cases = [("baidu", {"error_code": "58001"}, "unsupported_pair"),
                 ("youdao", {"errorCode": "102"}, "unsupported_pair"),
                 ("youdao", {"errorCode": "411"}, "quota"),
                 ("baidu", {"error_code": "52003"}, "authentication"),
                 ("libre", {}, "invalid_response"),
                 ("libre", {"translatedText": "&#32;"}, "invalid_response"),
                 ("youdao", {"errorCode": "0", "translation": "not a list"}, "invalid_response"),
                 ("google", {"data": {"translations": [None]}}, "invalid_response")]
        for provider, response, reason in cases:
            with self.subTest(provider=provider, reason=reason), TemporaryDirectory() as directory:
                translator = Translator(Path(directory))
                options = self.options(provider, **{provider + "_key": "key", provider + "_app_id": "app", provider + "_secret": "secret"})
                with patch("src.features.translation.service.post_json", return_value=response), self.assertRaises(TranslationError) as caught:
                    translator.translate("text", 10, Event(), options, source_language="fr", target_language="ja")
                self.assertEqual(caught.exception.reason, reason)
                self.assertFalse(list(Path(directory).rglob("*.txt")))
        for error, reason in ((HTTPError("https://example.org", 429, "rate", {}, None), "quota"), (TimeoutError(), "timeout")):
            with patch("src.features.translation.service.post_json", side_effect=error), self.assertRaises(TranslationError) as caught:
                request_translation("text", self.options("google", google_key="key"), Event())
            self.assertEqual(caught.exception.reason, reason)

    def test_partial_failure_and_cancellation_leave_no_cache(self):
        with TemporaryDirectory() as directory:
            translator = Translator(Path(directory))
            stop = Event()
            with patch("src.features.translation.service.request_translation", side_effect=["first", TranslationError("quota")]):
                with self.assertRaises(TranslationError):
                    translator.translate("word " * 180, 10, stop)
            self.assertFalse(list(Path(directory).rglob("*.txt")))
            def cancel(*args, **kwargs):
                stop.set()
                return "result"
            with patch("src.features.translation.service.request_translation", side_effect=cancel):
                with self.assertRaises(TaskCancelled):
                    translator.translate("text", 10, stop)
            self.assertFalse(list(Path(directory).rglob("*.txt")))

    def test_google_uses_official_post_and_key_header(self):
        options = self.options("google", google_key="private-key")
        with patch("src.features.translation.service.post_json", return_value={"data": {"translations": [{"translatedText": "中文 &amp; 内容"}]}}) as request:
            self.assertEqual(request_translation("Text", options, Event()), "中文 & 内容")
        self.assertNotIn("private-key", request.call_args.args[0])
        self.assertEqual(request.call_args.kwargs["headers"]["X-Goog-Api-Key"], "private-key")
        self.assertEqual(request.call_args.args[1]["target"], "zh-CN")

    def test_baidu_md5_signs_original_text_before_url_encoding(self):
        options = self.options("baidu", baidu_app_id="app", baidu_secret="secret")
        with patch("src.features.translation.service.token_hex", return_value="salt"), patch("src.features.translation.service.post_json", return_value={"trans_result": [{"dst": "译文"}]}) as request:
            self.assertEqual(request_translation("A & B", options, Event()), "译文")
        payload = request.call_args.args[1]
        self.assertEqual(payload["sign"], md5(b"appA & Bsaltsecret").hexdigest())
        self.assertTrue(request.call_args.kwargs["form"])
        self.assertEqual(payload["to"], "zh")
        self.assertNotIn("secret", payload)

    def test_youdao_v3_uses_shortened_input_and_timestamp(self):
        options = self.options("youdao", youdao_app_id="app", youdao_secret="secret")
        text = "A fairly long historical event summary"
        with patch("src.features.translation.service.token_hex", return_value="salt"), patch("src.features.translation.service.time", return_value=1700000000), patch("src.features.translation.service.post_json", return_value={"errorCode": "0", "translation": ["译文"]}) as request:
            self.assertEqual(request_translation(text, options, Event()), "译文")
        payload = request.call_args.args[1]
        expected = "app" + text[:10] + str(len(text)) + text[-10:] + "salt1700000000secret"
        self.assertEqual(payload["sign"], sha256(expected.encode()).hexdigest())
        self.assertEqual(payload["signType"], "v3")
        self.assertEqual(payload["to"], "zh-CHS")

    def test_libre_allows_self_hosting_without_key(self):
        options = self.options("libre", libre_url="http://localhost:5000/translate")
        with patch("src.features.translation.service.post_json", return_value={"translatedText": "译文"}) as request:
            self.assertEqual(request_translation("Text", options, Event()), "译文")
        self.assertNotIn("api_key", request.call_args.args[1])
        self.assertEqual(request.call_args.args[1]["target"], "zh")

    def test_providers_and_credentials_do_not_share_translation_cache(self):
        with TemporaryDirectory() as directory:
            translator = Translator(Path(directory))
            google = self.options("google", google_key="private-key")
            with patch("src.features.translation.service.get_json", return_value={"responseStatus": 200, "responseData": {"translatedText": "免费译文"}}) as anonymous, patch("src.features.translation.service.post_json", return_value={"data": {"translations": [{"translatedText": "谷歌译文"}]}}) as official:
                self.assertEqual(translator.translate("Original", 10, Event()), "免费译文")
                self.assertEqual(translator.translate("Original", 10, Event(), google), "谷歌译文")
                translator.translate("Original", 10, Event(), google)
                self.assertEqual(official.call_count, 1)
                changed = self.options("google", google_key="another-key")
                translator.translate("Original", 10, Event(), changed)
                self.assertEqual(official.call_count, 2)
                self.assertEqual(anonymous.call_count, 1)
            for path in Path(directory).rglob("*.txt"):
                self.assertNotIn("private-key", path.name + path.read_text(encoding="utf-8"))

    def test_error_traceback_does_not_include_credentials(self):
        options = self.options("google", google_key="private-key")
        with patch("src.features.translation.service.post_json", side_effect=ValueError("server echoed private-key")):
            try:
                request_translation("Text", options, Event())
            except ValueError as error:
                self.assertNotIn("private-key", "".join(traceback.format_exception(error)))
                self.assertEqual(error.ui_message.key, "translation.failure.request_failed")
            else:
                self.fail("Expected a sanitized failure")
