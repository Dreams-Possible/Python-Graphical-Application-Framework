"""可切换在线翻译适配器；签名、凭据和缓存与调用页面隔离。"""
from dataclasses import dataclass, field
from functools import lru_cache
from hashlib import md5, sha256
import html
import json
from secrets import token_hex
from time import time
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError

from src.features.translation.settings import PROVIDERS
from src.shared.errors import ui_error
from src.shared.http import get_json, post_json
from src.shared.messages import message
from src.shared.paths import resource_path
from src.shared.tasks import TaskCancelled, check_cancelled


class TranslationError(ValueError):
    """稳定的 reason 供调用方分流；ui_message 用于本地化展示。"""
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason.removeprefix("translation.")


# 明确列出已适配的公共语种；服务端账号/部署的实际可用范围仍以请求结果为准。
_COMMON = ("en", "zh-CN", "zh-TW", "ja", "ko", "fr", "de", "es", "pt", "ru", "it", "ar")
_LANGUAGES = {
    "mymemory": dict(zip(_COMMON, _COMMON)),
    "google": dict(zip(_COMMON, _COMMON)),
    "baidu": dict(zip(_COMMON, ("en", "zh", "cht", "jp", "kor", "fra", "de", "spa", "pt", "ru", "it", "ara"))),
    "youdao": dict(zip(_COMMON, ("en", "zh-CHS", "zh-CHT", "ja", "ko", "fr", "de", "es", "pt", "ru", "it", "ar"))),
    "libre": dict(zip(_COMMON, ("en", "zh", "zt", "ja", "ko", "fr", "de", "es", "pt", "ru", "it", "ar"))),
}


def supported_languages(provider):
    """返回适配器已映射的标准语言码，不承诺账号权限或自建实例模型可用。"""
    if provider not in _LANGUAGES:
        raise ui_error(TranslationError, "translation.unknown_provider")
    return tuple(_LANGUAGES[provider])


def normalize_language(language):
    value = language.strip().replace("_", "-").lower() if isinstance(language, str) else ""
    aliases = {"zh": "zh-CN", "zh-cn": "zh-CN", "zh-sg": "zh-CN", "zh-hans": "zh-CN",
               "zh-tw": "zh-TW", "zh-hk": "zh-TW", "zh-mo": "zh-TW", "zh-hant": "zh-TW"}
    if value in aliases:
        return aliases[value]
    if value in _COMMON:
        return value
    # 对非中文只接受常见地区后缀，不推断未知语言或自动检测。
    parts = value.split("-")
    if len(parts) == 2 and parts[0] in _COMMON and len(parts[1]) == 2 and parts[1].isalpha():
        return parts[0]
    raise ui_error(TranslationError, "translation.unsupported_language")


def _language_pair(provider, source, target):
    supported_languages(provider)
    source, target = normalize_language(source), normalize_language(target)
    return source, target, _LANGUAGES[provider][source], _LANGUAGES[provider][target]


def _failure(reason, provider, code="response"):
    error = ui_error(TranslationError, "translation.failure." + reason,
                     provider=message("translation.provider." + provider), code=code)
    error.reason = reason
    return error


@lru_cache(maxsize=1)
def default_values():
    return json.loads(resource_path("defaults/translation.json").read_text(encoding="utf-8"))["values"]


@dataclass(frozen=True)
class TranslationOptions:
    provider: str
    endpoint: str
    timeout: int = 10
    app_id: str = field(default="", repr=False)
    key: str = field(default="", repr=False)

    @classmethod
    def from_values(cls, values):
        merged = dict(default_values(), **values)
        provider = merged["provider"]
        if provider not in PROVIDERS:
            raise ui_error(ValueError, "translation.unknown_provider")
        key = merged.get(provider + "_secret", "") if provider in ("baidu", "youdao") else merged.get(provider + "_key", "")
        return cls(provider, merged[provider + "_url"].strip(), int(merged["timeout_seconds"]), merged.get(provider + "_app_id", "").strip(), key.strip())

    @property
    def signature(self):
        # 仅摘要进入缓存标识，凭据不进入路径、日志或对象 repr。
        value = json.dumps((self.provider, self.endpoint, self.app_id, self.key, self.timeout))
        return sha256(value.encode()).hexdigest()[:20]


def validate_options(options):
    supported_languages(options.provider)
    parsed = urlsplit(options.endpoint)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        error = ui_error(TranslationError, "errors.http_url")
        error.reason = "invalid_configuration"
        raise error
    if options.provider in ("google", "baidu", "youdao") and (not options.key or (options.provider in ("baidu", "youdao") and not options.app_id)):
        raise ui_error(TranslationError, "translation.credentials_required", provider=message("translation.provider." + options.provider))


def chunks(text):
    while text:
        end = 0
        for index in range(len(text)):
            if len(text[:index + 1].encode("utf-8")) > 450:
                break
            end = index + 1
        if end < len(text):
            space = text.rfind(" ", 0, end)
            if space > end // 2:
                end = space + 1
        yield text[:end]
        text = text[end:]


def _response_text(items, key=None):
    if not isinstance(items, list) or not items:
        raise TypeError("invalid translation list")
    values = [item[key] if key else item for item in items]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise TypeError("invalid translation text")
    return "\n".join(values)


def request_translation(text, options, stop, *, source_language="en", target_language="zh-CN"):
    provider = options.provider
    timeout = options.timeout
    check_cancelled(stop)
    source, target, source_code, target_code = _language_pair(provider, source_language, target_language)
    if not isinstance(text, str):
        raise TypeError("text must be str")
    if not text.strip() or source == target:
        return text
    validate_options(options)
    try:
        code = "response"
        if provider == "mymemory":
            doc = get_json(options.endpoint, {"q": text, "langpair": source_code + "|" + target_code}, timeout, stop)
            code = str(doc.get("responseStatus", "response"))
            value = doc.get("responseData", {}).get("translatedText") if code == "200" else None
        elif provider == "google":
            doc = post_json(options.endpoint, {"q": text, "source": source_code, "target": target_code, "format": "text"}, timeout, stop, headers={"X-Goog-Api-Key": options.key})
            value = _response_text(doc["data"]["translations"], "translatedText")
        elif provider == "baidu":
            salt = token_hex(16)
            sign = md5((options.app_id + text + salt + options.key).encode(), usedforsecurity=False).hexdigest()
            doc = post_json(options.endpoint, {"q": text, "from": source_code, "to": target_code, "appid": options.app_id, "salt": salt, "sign": sign}, timeout, stop, form=True)
            code = str(doc.get("error_code", "response"))
            value = _response_text(doc.get("trans_result"), "dst") if "error_code" not in doc else None
        elif provider == "youdao":
            salt, current = token_hex(16), str(int(time()))
            shortened = text if len(text) <= 20 else text[:10] + str(len(text)) + text[-10:]
            sign = sha256((options.app_id + shortened + salt + current + options.key).encode()).hexdigest()
            doc = post_json(options.endpoint, {"q": text, "from": source_code, "to": target_code, "strict": "true", "appKey": options.app_id, "salt": salt, "curtime": current, "signType": "v3", "sign": sign}, timeout, stop, form=True)
            code = str(doc.get("errorCode", "response"))
            value = _response_text(doc.get("translation")) if code == "0" else None
        else:
            payload = {"q": text, "source": source_code, "target": target_code, "format": "text"}
            if options.key:
                payload["api_key"] = options.key
            doc = post_json(options.endpoint, payload, timeout, stop)
            value = doc.get("translatedText")
        value = html.unescape(value) if isinstance(value, str) else value
        if not isinstance(value, str) or not value.strip():
            if (provider == "baidu" and code == "58001") or (provider == "youdao" and code == "102"):
                raise _failure("unsupported_pair", provider, code)
            if code in ("401", "403", "101", "202", "203", "54001", "52003"):
                raise _failure("authentication", provider, code)
            if code in ("429", "411", "412", "54003", "54004", "54005"):
                raise _failure("quota", provider, code)
            raise _failure("invalid_response", provider, code if code.isdigit() else "response")
        check_cancelled(stop)
        return value
    except TaskCancelled:
        raise
    except TranslationError:
        raise
    except Exception as error:
        code = str(getattr(error, "code", "")) or str(error)
        reason = "request_failed"
        if isinstance(error, HTTPError):
            reason = {401: "authentication", 403: "authentication", 429: "quota"}.get(error.code, reason)
        elif isinstance(error, TimeoutError) or isinstance(error, URLError) and isinstance(error.reason, TimeoutError):
            reason = "timeout"
        elif isinstance(error, (KeyError, TypeError, AttributeError)):
            reason = "invalid_response"
        raise _failure(reason, provider, code if code.isdigit() else "response") from None


class Translator:
    def __init__(self, cache):
        self.cache = cache / "translations"

    def translate(self, text, timeout, stop, options=None, *, source_language="en", target_language="zh-CN"):
        """后台线程中同步调用；失败抛 TranslationError，取消抛 TaskCancelled。

        未指定 options 时使用默认 MyMemory，而非隐式读取全局设置。
        同语种/空白直接返回原文；其他结果只有完整成功才缓存。
        """
        check_cancelled(stop)
        options = options or TranslationOptions.from_values({"timeout_seconds": timeout})
        source, target, _, _ = _language_pair(options.provider, source_language, target_language)
        if not isinstance(text, str):
            raise TypeError("text must be str")
        if not text.strip() or source == target:
            return text
        validate_options(options)
        key = sha256((options.signature + "|" + source + "|" + target + "|" + text).encode()).hexdigest()
        path = self.cache / (key + ".txt")
        try:
            value = path.read_text(encoding="utf-8")
            if value.strip():
                return value
        except OSError:
            pass
        values = []
        for part in chunks(text):
            check_cancelled(stop)
            values.append(request_translation(part, options, stop, source_language=source, target_language=target))
        value = " ".join(values)
        check_cancelled(stop)
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(value, encoding="utf-8")
            temporary.replace(path)
        except OSError:
            pass
        return value
