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
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from uuid import uuid4
import logging
from threading import Condition
from contextlib import contextmanager

from src.features.translation.settings import PROVIDERS
from src.shared.errors import ui_error
from src.shared.http import get_json, post_json
from src.shared.messages import message
from src.shared.paths import resource_path
from src.shared.tasks import TaskCancelled, check_cancelled

LOGGER = logging.getLogger("workbench.translation")


class _RequestLimiter:
    """所有集合共用请求配额，多个日期不能各自放大并发上限。"""
    def __init__(self):
        self.condition = Condition()
        self.active = 0

    @contextmanager
    def slot(self, limit, stop):
        with self.condition:
            while self.active >= limit:
                check_cancelled(stop)
                self.condition.wait(0.05)
            check_cancelled(stop)
            self.active += 1
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


_REQUEST_LIMITER = _RequestLimiter()


@dataclass(frozen=True)
class TranslationResult:
    """与输入位置一一对应；未调度项 skipped，失败项 error，成功项 text。"""
    text: str = ""
    error: Exception | None = None
    skipped: bool = False

    @property
    def succeeded(self):
        return self.error is None and not self.skipped


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


def preferred_target_language(language, provider):
    """优先对应语言；适配器未映射的语言统一回退英文，不用“非中文”推断。"""
    try:
        normalized = normalize_language(language)
        return normalized if normalized in supported_languages(provider) else "en"
    except TranslationError:
        return "en"


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
    max_workers: int = 10

    @classmethod
    def from_values(cls, values):
        merged = dict(default_values(), **values)
        provider = merged["provider"]
        if provider not in PROVIDERS:
            raise ui_error(ValueError, "translation.unknown_provider")
        key = merged.get(provider + "_secret", "") if provider in ("baidu", "youdao") else merged.get(provider + "_key", "")
        return cls(provider, merged[provider + "_url"].strip(), int(merged["timeout_seconds"]), merged.get(provider + "_app_id", "").strip(), key.strip(),
                   max_workers=merged["max_workers"])

    @property
    def signature(self):
        # 仅摘要进入缓存标识，凭据不进入路径、日志或对象 repr。
        value = json.dumps((self.provider, self.endpoint, self.app_id, self.key, self.timeout))
        return sha256(value.encode()).hexdigest()[:20]


def validate_options(options):
    supported_languages(options.provider)
    if type(options.max_workers) is not int or not 1 <= options.max_workers <= 10:
        raise ui_error(TranslationError, "errors.settings_invalid", field=message("settings.translation.max_workers"))
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


def request_translation_batch(texts, options, stop, source, target):
    """仅使用供应商原生数组协议，逐项检查数量及文本，不拼接分隔符。"""
    check_cancelled(stop)
    _, _, source_code, target_code = _language_pair(options.provider, source, target)
    validate_options(options)
    try:
        payload = {"q": texts, "source": source_code, "target": target_code, "format": "text"}
        if options.provider == "google":
            document = post_json(options.endpoint, payload, options.timeout, stop, headers={"X-Goog-Api-Key": options.key})
            items = document["data"]["translations"]
            if not isinstance(items, list):
                raise TypeError("invalid translation list")
            values = [item["translatedText"] for item in items]
        elif options.provider == "libre":
            if options.key:
                payload["api_key"] = options.key
            document = post_json(options.endpoint, payload, options.timeout, stop)
            values = document["translatedText"]
        else:
            raise TypeError("provider has no array adapter")
        if not isinstance(values, list) or len(values) != len(texts):
            raise TypeError("translation count mismatch")
        if any(not isinstance(value, str) or not html.unescape(value).strip() for value in values):
            raise TypeError("invalid translation text")
        check_cancelled(stop)
        return [html.unescape(value) for value in values]
    except TaskCancelled:
        raise
    except Exception as error:
        code = str(getattr(error, "code", ""))
        reason = "request_failed"
        if isinstance(error, HTTPError):
            reason = {401: "authentication", 403: "authentication", 429: "quota"}.get(error.code, reason)
        elif isinstance(error, TimeoutError) or isinstance(error, URLError) and isinstance(error.reason, TimeoutError):
            reason = "timeout"
        elif isinstance(error, (KeyError, TypeError, AttributeError)):
            reason = "invalid_response"
        raise _failure(reason, options.provider, code if code.isdigit() else "response") from None


class Translator:
    def __init__(self, cache):
        self.cache = cache / "translations"

    def _cache_path(self, text, options, source, target):
        key = sha256((options.signature + "|" + source + "|" + target + "|" + text).encode()).hexdigest()
        return self.cache / (key + ".txt")

    def _read_cache(self, path):
        try:
            value = path.read_text(encoding="utf-8")
            return value if value.strip() else None
        except (OSError, UnicodeError):
            return None

    def _save_cache(self, path, value):
        temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(value, encoding="utf-8")
            temporary.replace(path)
        except OSError:
            pass
        finally:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass

    def translate_many(self, texts, timeout, stop, options=None, *, source_language="en", target_language="zh-CN", use_cache=True, max_workers=None, on_result=None):
        """后台线程调用；原生数组组批或有限并发，按输入顺序返回 TranslationResult。

        单项失败不伪装成译文；认证/配额/语言组合拒绝后停止派发新请求。
        已在途请求无法强行终止，取消等待其超时或协作结束后抛 TaskCancelled。
        """
        check_cancelled(stop)
        if isinstance(texts, str):
            raise TypeError("texts must be a sequence of strings")
        texts = tuple(texts)
        if any(not isinstance(text, str) for text in texts):
            raise TypeError("texts must contain strings")
        options = options or TranslationOptions.from_values({"timeout_seconds": timeout})
        max_workers = options.max_workers if max_workers is None else max_workers
        if type(max_workers) is not int or not 1 <= max_workers <= 10:
            raise ValueError("max_workers must be between 1 and 10")
        source, target, _, _ = _language_pair(options.provider, source_language, target_language)
        results, missing = [None] * len(texts), []
        notified = set()

        def notify(index):
            if on_result and index not in notified and results[index] is not None:
                check_cancelled(stop)
                on_result(index, results[index])
                notified.add(index)
        for index, text in enumerate(texts):
            if not text.strip() or source == target:
                results[index] = TranslationResult(text)
                continue
            cached = self._read_cache(self._cache_path(text, options, source, target)) if use_cache else None
            if cached is not None:
                results[index] = TranslationResult(cached)
            else:
                missing.append(index)
            notify(index)
        if not missing:
            return tuple(results)
        try:
            validate_options(options)
        except (ValueError, OSError) as error:
            for index in missing:
                results[index] = TranslationResult(error=error)
                notify(index)
            return tuple(results)

        native = options.provider in ("google", "libre")
        work = []
        pieces = {}
        if native:
            group, size = [], 0
            for index in missing:
                parts = list(chunks(texts[index]))
                pieces[index] = [None] * len(parts)
                for position, part in enumerate(parts):
                    # 保守的请求上限；不假定所有自建实例都有同样容量。
                    if group and (len(group) >= 32 or size + len(part.encode()) > 4000):
                        work.append(group)
                        group, size = [], 0
                    group.append((index, position, part))
                    size += len(part.encode())
            if group:
                work.append(group)
        else:
            work = [[(index, 0, texts[index])] for index in missing]
        LOGGER.info("翻译集合开始：服务 %s，条目 %d，待处理 %d，模式 %s，并发上限 %d，请求组 %d",
                    options.provider, len(texts), len(missing), "batch" if native else "concurrent", max_workers, len(work))

        def execute(group):
            with _REQUEST_LIMITER.slot(max_workers, stop):
                if native:
                    return request_translation_batch([part for _, _, part in group], options, stop, source, target)
                return [self.translate(group[0][2], timeout, stop, options,
                                       source_language=source, target_language=target, use_cache=False)]

        executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="translation")
        pending, next_group, blocked = {}, 0, False
        try:
            while pending or next_group < len(work):
                check_cancelled(stop)
                while not blocked and len(pending) < max_workers and next_group < len(work):
                    check_cancelled(stop)
                    group = work[next_group]
                    pending[executor.submit(execute, group)] = group
                    next_group += 1
                if not pending:
                    break
                done, _ = wait(pending, timeout=0.05, return_when=FIRST_COMPLETED)
                for future in done:
                    group = pending.pop(future)
                    try:
                        values = future.result()
                        for (index, position, _), value in zip(group, values):
                            if native:
                                pieces[index][position] = value
                            else:
                                results[index] = TranslationResult(value)
                    except TaskCancelled:
                        raise
                    except Exception as error:
                        if not isinstance(error, TranslationError):
                            error = _failure("request_failed", options.provider)
                        for index, _, _ in group:
                            results[index] = TranslationResult(error=error)
                        if error.reason in ("quota", "authentication", "unsupported_pair", "credentials_required", "invalid_configuration"):
                            blocked = True
                    for index in {item[0] for item in group}:
                        parts = pieces.get(index)
                        if results[index] is None and parts and all(part is not None for part in parts):
                            results[index] = TranslationResult(" ".join(parts))
                        notify(index)
            check_cancelled(stop)
        finally:
            for future in pending:
                future.cancel()
            executor.shutdown(wait=True, cancel_futures=True)
        for index in missing:
            if results[index] is None:
                parts = pieces.get(index)
                results[index] = TranslationResult(" ".join(parts)) if parts and all(part is not None for part in parts) else TranslationResult(skipped=True)
            notify(index)
        check_cancelled(stop)
        if use_cache:
            for index in missing:
                if results[index].succeeded:
                    self._save_cache(self._cache_path(texts[index], options, source, target), results[index].text)
        LOGGER.info("翻译集合结束：成功 %d，失败 %d，未调度 %d", sum(result.succeeded for result in results),
                    sum(result.error is not None for result in results), sum(result.skipped for result in results))
        return tuple(results)

    def translate(self, text, timeout, stop, options=None, *, source_language="en", target_language="zh-CN", use_cache=True):
        """后台线程中同步调用；失败抛 TranslationError，取消抛 TaskCancelled。

        未指定 options 时使用默认 MyMemory，而非隐式读取全局设置。
        同语种/空白直接返回原文；其他结果只有完整成功才缓存。
        use_cache=False 允许业务模块自行组织集合缓存，不读取或生成逐条文件。
        """
        check_cancelled(stop)
        options = options or TranslationOptions.from_values({"timeout_seconds": timeout})
        source, target, _, _ = _language_pair(options.provider, source_language, target_language)
        if not isinstance(text, str):
            raise TypeError("text must be str")
        if not text.strip() or source == target:
            return text
        validate_options(options)
        path = self._cache_path(text, options, source, target)
        if use_cache:
            value = self._read_cache(path)
            if value is not None:
                return value
        values = []
        for part in chunks(text):
            check_cancelled(stop)
            values.append(request_translation(part, options, stop, source_language=source, target_language=target))
        value = " ".join(values)
        check_cancelled(stop)
        if not use_cache:
            return value
        self._save_cache(path, value)
        return value
