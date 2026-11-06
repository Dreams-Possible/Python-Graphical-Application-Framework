"""按月日查询维基历史事件；后台请求、单任务合并与按来源缓存。"""
from dataclasses import dataclass, field, replace
from src.features.translation.service import Translator, TranslationOptions
from src.shared.tasks import check_cancelled
from datetime import date
from hashlib import sha256
import json
import logging
from time import time
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal
from src.shared.errors import ui_error
from src.shared.http import get_json
from src.shared.messages import Message, message
from version import APP_VERSION

LOGGER = logging.getLogger("workbench.calendar.history")
TASK_KEY = "calendar.history"
CACHE_SECONDS = 24 * 3600


@dataclass(frozen=True)
class HistoryEvent:
    year: int
    text: str
    article: str = ""
    original_text: str = ""
    translation_status: str = ""


@dataclass(frozen=True)
class HistoryQuery:
    month: int
    day: int
    language: str
    template: str
    timeout: int
    target_language: str = "en"
    limit: int = 10
    refresh: bool = field(default=False, compare=False)
    translation: TranslationOptions = field(default_factory=lambda: TranslationOptions.from_values({}), repr=False)

    @property
    def key(self):
        digest = sha256(self.template.encode()).hexdigest()[:12]
        suffix = "-" + self.translation.signature if self.target_language == "zh" else ""
        return f"{digest}-{self.language}-{self.month:02d}-{self.day:02d}-{self.target_language}-{self.limit}{suffix}"

    @property
    def url(self):
        return self.template.format(language=self.language, month=f"{self.month:02d}", day=f"{self.day:02d}")


@dataclass(frozen=True)
class HistorySnapshot:
    query: HistoryQuery
    fetched_at: float
    events: tuple[HistoryEvent, ...]

    @property
    def complete(self):
        return self.query.target_language != "zh" or all(
            event.translation_status == "translated" for event in self.events[:self.query.limit])


@dataclass(frozen=True)
class HistoryState:
    key: str = ""
    events: tuple[HistoryEvent, ...] = ()
    status: Message = Message("calendar.history.idle")
    busy: bool = False
    language: str = "zh"
    total: int = 0


def safe_article(value):
    if not isinstance(value, str):
        return ""
    try:
        parts = urlsplit(value)
    except ValueError:
        return ""
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or parts.username or parts.password:
        return ""
    return value if host == "wikipedia.org" or host.endswith(".wikipedia.org") else ""


def parse_events(document):
    items = document.get("selected", document.get("events")) if isinstance(document, dict) else None
    if not isinstance(items, list):
        raise ui_error(ValueError, "calendar.history.invalid_response")
    entries, seen = [], set()
    for item in items:
        if not isinstance(item, dict) or type(item.get("year")) is not int or not isinstance(item.get("text"), str) or not item["text"].strip():
            raise ui_error(ValueError, "calendar.history.invalid_response")
        year, text = item["year"], item["text"].strip()
        if (year, text) in seen:
            continue
        seen.add((year, text))
        article = ""
        pages = item.get("pages", [])
        if isinstance(pages, list):
            for page in pages:
                if not isinstance(page, dict):
                    continue
                urls = page.get("content_urls", {})
                desktop = urls.get("desktop", {}) if isinstance(urls, dict) else {}
                article = safe_article(desktop.get("page")) if isinstance(desktop, dict) else ""
                if article:
                    break
        entries.append(HistoryEvent(year, text, article, item.get("original_text", ""), item.get("translation_status", "")))
    return tuple(sorted(entries, key=lambda entry: entry.year, reverse=True))


class HistoryRepository:
    def __init__(self, cache, now=time):
        self.cache = cache / "calendar" / "history"
        self.now = now
        self.translator = Translator(self.cache)

    def _path(self, query):
        date(2000, query.month, query.day)
        name = "translated.json" if query.target_language == "zh" else "source.json"
        return self.cache / f"{query.month:02d}-{query.day:02d}" / name

    def _source_key(self, query):
        return sha256(f"{query.template}|{query.language}|{query.month:02d}-{query.day:02d}".encode()).hexdigest()

    def _translation_key(self, query):
        return self._source_key(query) + "|" + query.target_language + "|" + query.translation.signature

    @staticmethod
    def _source_hash(events):
        values = [(event.year, event.original_text or event.text, event.article) for event in events]
        return sha256(json.dumps(values, ensure_ascii=False).encode()).hexdigest()

    def read(self, query):
        try:
            doc = json.loads(self._path(query).read_text(encoding="utf-8"))
            key = self._translation_key(query) if query.target_language == "zh" else self._source_key(query)
            if query.target_language == "zh":
                raw = self.read(replace(query, target_language="en"))
                if (raw is None or doc["schema_version"] != 2 or doc["key"] != key
                        or doc["source_hash"] != self._source_hash(raw.events)):
                    return None
                translations = doc["translations"]
                if not isinstance(translations, dict):
                    return None
                valid_indices = {str(i) for i in range(len(raw.events))}
                for index, text in translations.items():
                    if index not in valid_indices or not isinstance(text, str) or not text.strip():
                        return None
                # 原文、年份、来源链接只从英文集合读取；缺失译文自动视为待补齐。
                events = tuple(replace(event, text=translations.get(str(index), event.text), original_text=event.text,
                                       translation_status="translated" if str(index) in translations else "pending")
                               for index, event in enumerate(raw.events))
                return HistorySnapshot(query, raw.fetched_at, events)
            if doc["schema_version"] != 1 or doc["key"] != key or type(doc["fetched_at"]) not in (int, float):
                return None
            events = []
            for item in doc["events"]:
                if type(item["year"]) is not int or not isinstance(item["text"], str) or not item["text"].strip():
                    return None
                if not isinstance(item.get("original_text", ""), str):
                    return None
                events.append(HistoryEvent(item["year"], item["text"], safe_article(item.get("article", "")),
                                          item.get("original_text", ""), item.get("translation_status", "")))
            events = tuple(sorted(events, key=lambda entry: entry.year, reverse=True))
            return HistorySnapshot(query, doc["fetched_at"], events)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def fetch(self, query, stop):
        user_agent = f"Daylight/{APP_VERSION} (https://github.com/Dreams-Possible/Python-Graphical-Application-Framework)"
        raw_query = replace(query, target_language="en", limit=100, refresh=False)
        raw = self.read(raw_query)
        if query.refresh or raw is None or not 0 <= self.now() - raw.fetched_at < CACHE_SECONDS:
            doc = get_json(query.url, {}, query.timeout, stop, user_agent=user_agent)
            raw = HistorySnapshot(raw_query, self.now(), parse_events(doc))
            self.save(raw)
        events = raw.events
        if query.target_language == "zh":
            # 一天作为一个翻译任务与缓存单元；仅补齐当前显示范围内缺失的译文。
            cached = self.read(query)
            translated, missing = [], []
            for index, event in enumerate(events):
                check_cancelled(stop)
                previous = cached.events[index] if cached else None
                if previous and previous.translation_status == "translated":
                    translated.append(previous)
                    continue
                translated.append(replace(event, original_text=event.text, translation_status="pending"))
                if index < query.limit:
                    missing.append(index)
            results = self.translator.translate_many([events[index].text for index in missing], query.timeout, stop,
                query.translation, source_language="en", target_language="zh-CN", use_cache=False)
            for index, result in zip(missing, results):
                if result.succeeded:
                    translated[index] = replace(translated[index], text=result.text, translation_status="translated")
                elif result.error:
                    LOGGER.warning("历史事件翻译失败，保留原文：%s", getattr(result.error, "reason", type(result.error).__name__))
                    translated[index] = replace(translated[index], translation_status="failed")
            events = tuple(translated)
        check_cancelled(stop)
        return HistorySnapshot(query, raw.fetched_at, events)

    def save(self, snapshot):
        translated = snapshot.query.target_language == "zh"
        if translated:
            doc = {"schema_version": 2, "key": self._translation_key(snapshot.query),
                   "source_hash": self._source_hash(snapshot.events),
                   "translations": {str(index): entry.text for index, entry in enumerate(snapshot.events)
                                    if entry.translation_status == "translated"}}
        else:
            doc = {"schema_version": 1, "key": self._source_key(snapshot.query),
                   "month_day": f"{snapshot.query.month:02d}-{snapshot.query.day:02d}",
                   "source_language": snapshot.query.language, "fetched_at": snapshot.fetched_at,
                   "events": [{"year": entry.year, "text": entry.text, "article": entry.article}
                              for entry in snapshot.events]}
        try:
            target = self._path(snapshot.query)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            temporary.replace(target)
        except OSError:
            LOGGER.warning("History cache could not be saved", exc_info=True)


class HistoryService(QObject):
    changed = Signal()

    def __init__(self, tasks, configuration, repository, texts):
        super().__init__()
        self.tasks, self.configuration, self.repository = tasks, configuration, repository
        self.texts = texts
        texts.changed.connect(self._language_changed)
        self.state = HistoryState()
        self._generation = -1
        self._pending = None
        self._current = None
        self._memo = {}
        self._active = False
        self._stopped = False
        self._date = None
        self._values = self._settings()
        tasks.completed.connect(self._completed)
        tasks.activity_changed.connect(self._try_pending)
        configuration.changed.connect(self._configured)

    def _settings(self):
        values = self.configuration.get("calendar")
        return dict({key: values[key] for key in ("history_enabled", "history_url", "history_limit", "timeout_seconds")}, translation=TranslationOptions.from_values(self.configuration.get("translation")))

    def _publish(self, query, snapshot, status, busy=False):
        events = snapshot.events[:self._values["history_limit"]] if snapshot else ()
        if not busy and query and query.target_language == "zh" and any(event.translation_status in ("failed", "pending") for event in events):
            status = message("calendar.history.translation_partial")
        state = HistoryState(query.key if query else "", events, status, busy, query.target_language if query else ("zh" if self.texts.language == "zh-CN" else "en"), len(snapshot.events) if snapshot else 0)
        if state != self.state:
            self.state = state
            self.changed.emit()

    def load(self, day, force=False):
        if self._stopped:
            return
        self._active, self._date = True, day
        if not self._values["history_enabled"]:
            self.suspend()
            self._active = True  # 保留日视图的订阅意图，重新启用后可立即加载。
            self._publish(None, None, message("calendar.history.disabled"))
            return
        query = HistoryQuery(day.month, day.day, "en", self._values["history_url"], self._values["timeout_seconds"], target_language="zh" if self.texts.language == "zh-CN" else "en", limit=self._values["history_limit"], refresh=force, translation=self._values["translation"])
        date(2000, query.month, query.day)  # 月日查询也允许 2 月 29 日。
        snapshot = self._memo.get(query.key)
        if snapshot is None:
            snapshot = self.repository.read(query)
            if snapshot:
                self._memo[query.key] = snapshot
        if not force and self._current == query and self._generation >= 0 and self.tasks.is_active(TASK_KEY):
            return
        age = self.repository.now() - snapshot.fetched_at if snapshot else None
        if not force and snapshot and snapshot.complete and 0 <= age < CACHE_SECONDS:
            if self.tasks.is_active(TASK_KEY):
                self.tasks.cancel(TASK_KEY)
                self._generation = -1
            self._current = query
            self._pending = None
            self._publish(query, snapshot, message("calendar.history.cached"))
            return
        self._current = query
        self._publish(query, snapshot, message("calendar.history.loading_cached" if snapshot else "calendar.history.loading"), True)
        if self.tasks.is_active(TASK_KEY):
            self.tasks.cancel(TASK_KEY)
            self._generation = -1
            self._pending = query
            return
        self._submit(query)

    def _submit(self, query):
        self._pending = None
        try:
            self._generation = self.tasks.submit(TASK_KEY, lambda stop: self.repository.fetch(query, stop))
        except RuntimeError:
            self._publish(query, self._memo.get(query.key), message("calendar.history.failed"))

    def _try_pending(self, *_):
        if self._pending and self._active and not self._stopped and not self.tasks.is_active(TASK_KEY):
            self._submit(self._pending)

    def _completed(self, key, generation, result, error, cancelled):
        if key != TASK_KEY or generation != self._generation or not self._active or self._stopped:
            return
        query = self._current
        if error or cancelled:
            cached = self._memo.get(query.key)
            self._publish(query, cached, message("calendar.history.failed_cached" if cached else "calendar.history.failed"))
            return
        if not isinstance(result, HistorySnapshot) or result.query != query:
            return
        self._memo[query.key] = result
        self.repository.save(result)
        self._publish(query, result, message("calendar.history.loaded" if result.events else "calendar.history.empty"))

    def suspend(self):
        self._active = False
        self._pending = None
        self._generation = -1
        if self.tasks.is_active(TASK_KEY):
            self.tasks.cancel(TASK_KEY)
        if self.state.busy:
            self._publish(self._current, self._memo.get(self.state.key), message("calendar.history.idle"))

    def _configured(self, module):
        if module not in ("calendar", "translation"):
            return
        values = self._settings()
        if values == self._values:
            return
        if module == "translation" and self.texts.language != "zh-CN":
            self._values = values
            return
        active, day = self._active, self._date
        self.suspend()
        self._values = values
        self._memo.clear()
        self._publish(None, None, message("calendar.history.idle"))
        if active and day:
            self.load(day)

    def _language_changed(self):
        if self._active and self._date:
            self.load(self._date)

    def stop(self):
        self.suspend()
        self._stopped = True
