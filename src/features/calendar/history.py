"""按月日查询维基历史事件；后台请求、单任务合并与按来源缓存。"""
from dataclasses import dataclass, field, replace
from src.features.translation.service import Translator, TranslationOptions, normalize_language, preferred_target_language
from src.shared.tasks import check_cancelled
from datetime import date, timedelta
from hashlib import sha256
import json
import logging
from time import time
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal, QTimer, Qt
from src.shared.errors import ui_error
from src.shared.http import get_json
from src.shared.messages import Message, message
from version import APP_VERSION

LOGGER = logging.getLogger("workbench.calendar.history")
TASK_KEY = "calendar.history"
CACHE_SECONDS = 24 * 3600
PRELOAD_CONCURRENT_DAYS = 3


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

    def __post_init__(self):
        object.__setattr__(self, "target_language", normalize_language(self.target_language))

    @property
    def needs_translation(self):
        return self.target_language != "en"

    @property
    def key(self):
        digest = sha256(self.template.encode()).hexdigest()[:12]
        suffix = "-" + self.translation.signature if self.needs_translation else ""
        return f"{digest}-{self.language}-{self.month:02d}-{self.day:02d}-{self.target_language}-{self.limit}{suffix}"

    @property
    def url(self):
        return self.template.format(language=self.language, month=f"{self.month:02d}", day=f"{self.day:02d}")


@dataclass(frozen=True)
class HistorySnapshot:
    query: HistoryQuery
    fetched_at: float
    events: tuple[HistoryEvent, ...]
    translation_error: str = ""
    phase: str = "ready"

    @property
    def complete(self):
        return not self.query.needs_translation or all(
            event.translation_status == "translated" for event in self.events[:self.query.limit])


@dataclass(frozen=True)
class HistoryState:
    key: str = ""
    events: tuple[HistoryEvent, ...] = ()
    status: Message = Message("calendar.history.idle")
    busy: bool = False
    language: str = "en"
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
        name = "translated.json" if query.needs_translation else "source.json"
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
            key = self._translation_key(query) if query.needs_translation else self._source_key(query)
            if query.needs_translation:
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

    def fetch_source(self, query, stop):
        """独立取得并保存英文集合；后续翻译的失败和取消不影响该文件。"""
        user_agent = f"Daylight/{APP_VERSION} (https://github.com/Dreams-Possible/Python-Graphical-Application-Framework)"
        raw_query = replace(query, target_language="en", limit=100, refresh=False)
        raw = self.read(raw_query)
        translated = self.read(query) if query.needs_translation and raw else None
        translation_only = raw is not None and query.needs_translation and (translated is None or not translated.complete)
        if query.refresh or raw is None or (not translation_only and not 0 <= self.now() - raw.fetched_at < CACHE_SECONDS):
            doc = get_json(query.url, {}, query.timeout, stop, user_agent=user_agent)
            raw = HistorySnapshot(raw_query, self.now(), parse_events(doc))
            self.save(raw)
        return raw

    def fetch(self, query, stop, on_progress=None):
        raw = self.fetch_source(query, stop)
        events = raw.events
        translation_error = ""
        if query.needs_translation:
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
            if on_progress:
                on_progress(HistorySnapshot(query, raw.fetched_at, tuple(translated), phase="translating"))
            handled = set()

            def apply_result(position, result):
                nonlocal translation_error
                index = missing[position]
                if result.succeeded:
                    translated[index] = replace(translated[index], text=result.text, translation_status="translated")
                elif result.error:
                    reason = getattr(result.error, "reason", "request_failed")
                    if translation_error not in ("quota", "authentication", "credentials_required", "unsupported_pair", "invalid_configuration"):
                        translation_error = reason
                    LOGGER.warning("历史事件翻译失败，保留原文：%s", getattr(result.error, "reason", type(result.error).__name__))
                    translated[index] = replace(translated[index], translation_status="failed")
                handled.add(position)
                if on_progress:
                    on_progress(HistorySnapshot(query, raw.fetched_at, tuple(translated), translation_error, "translating"))

            results = self.translator.translate_many([events[index].text for index in missing], query.timeout, stop,
                query.translation, source_language="en", target_language=query.target_language, use_cache=False, on_result=apply_result)
            for position, result in enumerate(results):
                if position not in handled:
                    apply_result(position, result)
            events = tuple(translated)
        check_cancelled(stop)
        return HistorySnapshot(query, raw.fetched_at, events, translation_error)

    def save(self, snapshot):
        translated = snapshot.query.needs_translation
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
    progress_ready = Signal(str, int, object)

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
        self._preload_started = False
        self._today = date.today
        self._background = {}
        self._preload_queue = []
        self._preload_epoch = 0
        self._preload_blocked = False
        self._waiting_background = None
        self._progress_sequence = 0
        self._progress_tokens = {}
        self.progress_ready.connect(self._progress, Qt.ConnectionType.QueuedConnection)
        self._preload_timer = QTimer(self)
        self._preload_timer.timeout.connect(self.preload)
        self._values = self._settings()
        tasks.completed.connect(self._completed)
        tasks.activity_changed.connect(self._try_pending)
        configuration.changed.connect(self._configured)

    def _settings(self):
        values = self.configuration.get("calendar")
        return dict({key: values[key] for key in ("history_enabled", "history_url", "history_limit", "timeout_seconds")},
                    history_preload=values.get("history_preload", True),
                    history_preload_days=values.get("history_preload_days", 7),
                    history_preload_minutes=values.get("history_preload_minutes", 60),
                    translation=TranslationOptions.from_values(self.configuration.get("translation")))

    def _query(self, day, force=False):
        return HistoryQuery(day.month, day.day, "en", self._values["history_url"], self._values["timeout_seconds"],
            target_language=self._target_language(), limit=self._values["history_limit"],
            refresh=force, translation=self._values["translation"])

    def _target_language(self):
        return preferred_target_language(self.texts.language, self._values["translation"].provider)

    def _submit_fetch(self, key, query):
        self._progress_sequence += 1
        token = self._progress_sequence
        self._progress_tokens[key] = token
        return self.tasks.submit(key, lambda stop: self.repository.fetch(query, stop,
            on_progress=lambda snapshot: self.progress_ready.emit(key, token, snapshot)))

    def _progress(self, key, token, snapshot):
        if self._stopped or self._progress_tokens.get(key) != token:
            return
        if key != TASK_KEY and key not in self._background:
            return
        if key == TASK_KEY and (self._generation < 0 or not self._active):
            return
        query = snapshot.query
        self._memo[query.key] = snapshot
        if self._active and self._current and self._current.key == query.key:
            done = sum(event.translation_status == "translated" for event in snapshot.events[:query.limit])
            self._publish(query, snapshot, message("calendar.history.translating", done=done, total=min(query.limit, len(snapshot.events))), True)

    def _cached(self, query):
        snapshot = self._memo.get(query.key)
        if snapshot is None:
            snapshot = self.repository.read(query)
            if snapshot is None and query.needs_translation:
                raw = self.repository.read(replace(query, target_language="en"))
                if raw:
                    snapshot = HistorySnapshot(query, raw.fetched_at, tuple(
                        replace(event, original_text=event.text, translation_status="pending") for event in raw.events))
            if snapshot:
                self._memo[query.key] = snapshot
        return snapshot

    def _fresh(self, snapshot):
        return snapshot is not None and snapshot.complete and 0 <= self.repository.now() - snapshot.fetched_at < CACHE_SECONDS

    def start_preload(self, today=None):
        """由启动入口调用；日期函数可读取独立当前位置时区，不依赖天气城市。"""
        if self._stopped:
            return
        if today is not None:
            self._today = today
        self._preload_started = True
        self._configure_preload_timer()
        self.preload()

    def _preload_enabled(self):
        return self._preload_started and not self._stopped and self._values["history_enabled"] and self._values["history_preload"]

    def _configure_preload_timer(self):
        self._preload_timer.setInterval(self._values["history_preload_minutes"] * 60000)
        self._preload_timer.start() if self._preload_enabled() else self._preload_timer.stop()

    def preload(self):
        if not self._preload_enabled():
            return
        self._preload_blocked = False
        today = self._today()
        if hasattr(today, "toPython"):
            today = today.toPython()
        queued = {query.key for query in self._preload_queue}
        queued.update(query.key for _, query in self._background.values())
        # 今天优先，再按距离交替扩展；跨年仍按月日集合缓存。
        offsets = [0] + [offset for distance in range(1, self._values["history_preload_days"] + 1) for offset in (-distance, distance)]
        added = 0
        for offset in offsets:
            try:
                query = self._query(today + timedelta(days=offset))
            except OverflowError:
                continue
            if query.key in queued or self._fresh(self._cached(query)):
                continue
            if self._active and self._current and query.key == self._current.key and (self._pending or self.tasks.is_active(TASK_KEY)):
                continue
            self._preload_queue.append(query)
            queued.add(query.key)
            added += 1
        LOGGER.info("历史预加载检查：范围 ±%d 天，新增 %d 个日期，后台在途 %d", self._values["history_preload_days"], added, len(self._background))
        self._pump_preload()

    def _pump_preload(self):
        if not self._preload_enabled() or self._preload_blocked:
            return
        while self._preload_queue and len(self._background) < PRELOAD_CONCURRENT_DAYS:
            query = self._preload_queue.pop(0)
            if self._fresh(self._cached(query)):
                continue
            if self._active and self._current and query.key == self._current.key and (self._pending or self.tasks.is_active(TASK_KEY)):
                continue
            key = f"calendar.history.preload.{self._preload_epoch}.{query.key}"
            if self.tasks.is_active(key):
                self._preload_queue.insert(0, query)
                break
            try:
                generation = self._submit_fetch(key, query)
            except RuntimeError:
                self._preload_queue.insert(0, query)
                break
            self._background[key] = (generation, query)

    def _cancel_preload(self):
        for key in self._background:
            self.tasks.cancel(key)
        self._background.clear()
        self._progress_tokens = {key: token for key, token in self._progress_tokens.items() if key == TASK_KEY}
        self._preload_queue.clear()
        self._preload_epoch += 1
        self._preload_blocked = False
        self._waiting_background = None

    def _background_completed(self, key, generation, result, error, cancelled):
        expected, query = self._background.get(key, (-1, None))
        if generation != expected or self._stopped:
            return
        del self._background[key]
        self._progress_tokens.pop(key, None)
        succeeded = not error and not cancelled and isinstance(result, HistorySnapshot) and result.query == query
        if succeeded:
            self._memo[query.key] = result
            self.repository.save(result)
        if (self._active and self._current and self._current.key == query.key
                and (self._waiting_background == query.key or not self.tasks.is_active(TASK_KEY))):
            self._waiting_background = None
            snapshot = result if succeeded else self._memo.get(query.key)
            self._publish(query, snapshot, message("calendar.history.loaded" if result.events else "calendar.history.empty") if succeeded
                          else message("calendar.history.failed_cached" if snapshot else "calendar.history.failed"))
        if succeeded and result.translation_error in ("quota", "authentication", "credentials_required", "unsupported_pair", "invalid_configuration"):
            LOGGER.warning("历史预加载停止本轮：%s", result.translation_error)
            self._preload_queue.clear()
            for other in self._background:
                self.tasks.cancel(other)
            self._preload_blocked = True
        self._pump_preload()

    def _publish(self, query, snapshot, status, busy=False):
        events = snapshot.events[:self._values["history_limit"]] if snapshot else ()
        if (not busy and query and query.needs_translation and any(event.translation_status in ("failed", "pending") for event in events)
                and (snapshot.translation_error or status.key in ("calendar.history.loaded", "calendar.history.cached", "calendar.history.empty"))):
            status = message("calendar.history.translation_quota" if snapshot.translation_error == "quota" else "calendar.history.translation_partial")
        state = HistoryState(query.key if query else "", events, status, busy, query.target_language if query else self._target_language(), len(snapshot.events) if snapshot else 0)
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
        query = self._query(day, force)
        date(2000, query.month, query.day)  # 月日查询也允许 2 月 29 日。
        snapshot = self._cached(query)
        if not force and self._current == query and self._generation >= 0 and self.tasks.is_active(TASK_KEY):
            return
        age = self.repository.now() - snapshot.fetched_at if snapshot else None
        if not force and snapshot and snapshot.complete and 0 <= age < CACHE_SECONDS:
            if self.tasks.is_active(TASK_KEY):
                self.tasks.cancel(TASK_KEY)
                self._generation = -1
            self._current = query
            self._pending = None
            self._waiting_background = None
            self._publish(query, snapshot, message("calendar.history.cached"))
            return
        self._current = query
        self._publish(query, snapshot, message("calendar.history.loading_cached" if snapshot else "calendar.history.loading"), True)
        self._waiting_background = None
        self._preload_queue = [item for item in self._preload_queue if item.key != query.key]
        for key, (_, background_query) in tuple(self._background.items()):
            if background_query.key != query.key:
                continue
            if force:
                self.tasks.cancel(key)
                del self._background[key]
                break
            if self.tasks.is_active(TASK_KEY):
                self.tasks.cancel(TASK_KEY)
            self._generation = -1
            self._pending = None
            self._waiting_background = query.key
            return
        if self.tasks.is_active(TASK_KEY):
            self.tasks.cancel(TASK_KEY)
            self._generation = -1
            self._pending = query
            return
        self._submit(query)

    def _submit(self, query):
        self._pending = None
        try:
            self._generation = self._submit_fetch(TASK_KEY, query)
        except RuntimeError:
            self._publish(query, self._memo.get(query.key), message("calendar.history.failed"))

    def _try_pending(self, *_):
        if self._pending and self._active and not self._stopped and not self.tasks.is_active(TASK_KEY):
            self._submit(self._pending)
        self._pump_preload()

    def _completed(self, key, generation, result, error, cancelled):
        if key in self._background:
            self._background_completed(key, generation, result, error, cancelled)
            return
        if key != TASK_KEY or generation != self._generation or not self._active or self._stopped:
            return
        query = self._current
        self._progress_tokens.pop(key, None)
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
        self._progress_tokens.pop(TASK_KEY, None)
        self._waiting_background = None
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
        if (module == "translation" and self._target_language() == "en"
                and preferred_target_language(self.texts.language, values["translation"].provider) == "en"):
            self._values = values
            return
        active, day = self._active, self._date
        self.suspend()
        self._cancel_preload()
        self._values = values
        self._memo.clear()
        self._publish(None, None, message("calendar.history.idle"))
        if active and day:
            self.load(day)
        self._configure_preload_timer()
        self.preload()

    def _language_changed(self):
        self._cancel_preload()
        if self._active and self._date:
            self.load(self._date)
        self.preload()

    def stop(self):
        self._preload_timer.stop()
        self._cancel_preload()
        self.suspend()
        self._stopped = True
