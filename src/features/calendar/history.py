"""按月日查询维基历史事件；后台请求、单任务合并与按来源缓存。"""
from dataclasses import dataclass
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


@dataclass(frozen=True)
class HistoryQuery:
    month: int
    day: int
    language: str
    template: str
    timeout: int

    @property
    def key(self):
        digest = sha256(self.template.encode()).hexdigest()[:12]
        return f"{digest}-{self.language}-{self.month:02d}-{self.day:02d}"

    @property
    def url(self):
        return self.template.format(language=self.language, month=f"{self.month:02d}", day=f"{self.day:02d}")


@dataclass(frozen=True)
class HistorySnapshot:
    query: HistoryQuery
    fetched_at: float
    events: tuple[HistoryEvent, ...]


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
        entries.append(HistoryEvent(year, text, article))
    return tuple(sorted(entries, key=lambda entry: entry.year))


class HistoryRepository:
    def __init__(self, cache, now=time):
        self.cache = cache / "calendar" / "history"
        self.now = now

    def read(self, query):
        try:
            doc = json.loads((self.cache / f"{query.key}.json").read_text(encoding="utf-8"))
            if doc["key"] != query.key or type(doc["fetched_at"]) not in (int, float):
                return None
            events = parse_events({"events": [{"year": item["year"], "text": item["text"],
                "pages": [{"content_urls": {"desktop": {"page": item.get("article", "")}}}]} for item in doc["events"]]})
            return HistorySnapshot(query, doc["fetched_at"], events)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def fetch(self, query, stop):
        user_agent = f"Daylight/{APP_VERSION} (https://github.com/Dreams-Possible/Python-Graphical-Application-Framework)"
        doc = get_json(query.url, {}, query.timeout, stop, user_agent=user_agent)
        return HistorySnapshot(query, self.now(), parse_events(doc))

    def save(self, snapshot):
        doc = {"key": snapshot.query.key, "fetched_at": snapshot.fetched_at,
               "events": [{"year": entry.year, "text": entry.text, "article": entry.article} for entry in snapshot.events]}
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
            target = self.cache / f"{snapshot.query.key}.json"
            temporary = target.with_suffix(".tmp")
            temporary.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            temporary.replace(target)
        except OSError:
            LOGGER.warning("History cache could not be saved", exc_info=True)


class HistoryService(QObject):
    changed = Signal()

    def __init__(self, tasks, configuration, repository):
        super().__init__()
        self.tasks, self.configuration, self.repository = tasks, configuration, repository
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
        return {key: values[key] for key in ("history_enabled", "history_url", "history_language", "history_limit", "timeout_seconds")}

    def _publish(self, query, snapshot, status, busy=False):
        events = snapshot.events[:self._values["history_limit"]] if snapshot else ()
        state = HistoryState(query.key if query else "", events, status, busy, query.language if query else self._values["history_language"], len(snapshot.events) if snapshot else 0)
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
        query = HistoryQuery(day.month, day.day, self._values["history_language"], self._values["history_url"], self._values["timeout_seconds"])
        date(2000, query.month, query.day)  # 月日查询也允许 2 月 29 日。
        snapshot = self._memo.get(query.key)
        if snapshot is None:
            snapshot = self.repository.read(query)
            if snapshot:
                self._memo[query.key] = snapshot
        if not force and self._current == query and self._generation >= 0 and self.tasks.is_active(TASK_KEY):
            return
        age = self.repository.now() - snapshot.fetched_at if snapshot else None
        if not force and snapshot and 0 <= age < CACHE_SECONDS:
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
        if module != "calendar":
            return
        values = self._settings()
        if values == self._values:
            return
        active, day = self._active, self._date
        self.suspend()
        self._values = values
        self._memo.clear()
        self._publish(None, None, message("calendar.history.idle"))
        if active and day:
            self.load(day)

    def stop(self):
        self.suspend()
        self._stopped = True
