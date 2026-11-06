"""冻结请求参数，隔离地点搜索和天气更新，拒绝过期结果。"""

from src.shared.errors import error_message

from dataclasses import replace
from src.shared.messages import message
import logging

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from src.features.weather.models import WeatherState
from src.features.weather.providers import ProviderRegistry
from src.shared.configuration import Configuration
from src.shared.tasks import TaskRunner

LOGGER = logging.getLogger("workbench.weather")


class WeatherViewModel(QObject):
    changed = Signal(object)
    search_changed = Signal(object)
    alert = Signal(object)

    def __init__(self, configuration: Configuration, tasks: TaskRunner, providers: ProviderRegistry) -> None:
        super().__init__()
        self.configuration, self.tasks, self.providers = configuration, tasks, providers
        self._state = WeatherState()
        self._search_state = WeatherState()
        self._preview_location = None
        self._preview_generation = -1
        self._preview_pending = False
        self._fetch_generation = 0
        self._search_generation = 0
        self._values = configuration.get("weather")
        self._current_location = None
        self._active = False
        self._pending = False
        self._stopped = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._configure_timer()
        configuration.changed.connect(self._configured)
        tasks.completed.connect(self._completed)
        tasks.activity_changed.connect(self._try_pending)

    @property
    def state(self) -> WeatherState:
        return self._state

    @property
    def search_state(self) -> WeatherState:
        return self._search_state

    def _set_search(self, **changes) -> None:
        updated = replace(self._search_state, **changes)
        if updated != self._search_state:
            self._search_state = updated
            if self._active:
                self.search_changed.emit(updated)

    def _set(self, **changes) -> None:
        updated = replace(self._state, **changes)
        if updated != self._state:
            self._state = updated
            if self._active:
                self.changed.emit(updated)

    def set_active(self, active: bool) -> None:
        self._active = active
        if active:
            self.changed.emit(self._state)
            self.search_changed.emit(self._search_state)

    def set_current_location(self, fix) -> None:
        previous, self._current_location = self._current_location, fix
        if self._stopped or previous == fix:
            return
        self.tasks.cancel("weather.fetch")
        self._fetch_generation = -1
        self._pending = False
        self._set(report=None, busy=False, error="", status=message("weather.state.location_changed" if fix else "weather.state.waiting_location"))
        if fix and self._values["auto_refresh"]:
            self._pending = True
            QTimer.singleShot(0, self._try_pending)

    def search(self, query: str) -> None:
        query = query.strip()
        if not query:
            LOGGER.warning("地点搜索未执行：查询为空")
            self._set_search(error=message("weather.search.required"))
            return
        if self._search_state.searching:
            LOGGER.debug("忽略重复地点搜索：上一请求仍在执行")
            return
        try:
            self.tasks.cancel("weather.preview")
            self._preview_generation = -1
            self._preview_pending = False
            self._preview_location = None
            self.configuration.update("weather", search_query=query)
            LOGGER.info("开始地点搜索（不记录搜索内容）")
            values = self.configuration.get("weather")
            provider = self.providers.get(values["provider"])
            self._search_generation = self.tasks.submit("weather.search", lambda stop: provider.search(query, values, stop))
        except (ValueError, OSError, RuntimeError) as error:
            LOGGER.warning("地点搜索无法启动：%s", type(error).__name__)
            self._set_search(error=error_message(error))
            return
        self._set_search(searching=True, busy=False, locations=(), report=None, error="", status=message("weather.search.running"))

    def select_location(self, index: int) -> None:
        if not 0 <= index < len(self._search_state.locations):
            return
        self._preview_location = self._search_state.locations[index]
        LOGGER.info("用户选择搜索结果：第 %d 项，仅更新搜索天气", index + 1)
        self._preview_pending = True
        self._preview_generation = -1
        self._set_search(report=None, busy=True, error="", status=message("weather.state.updating", location=self._preview_location.name))
        if self.tasks.is_active("weather.preview"):
            self.tasks.cancel("weather.preview")
            return
        self._fetch_preview()

    def _fetch_preview(self):
        if self._stopped or self._preview_location is None:
            return
        location = self._preview_location
        values = self.configuration.get("weather")
        values.update(location_name=location.name, latitude=location.latitude, longitude=location.longitude)
        provider = self.providers.get(values["provider"])
        try:
            self._preview_generation = self.tasks.submit("weather.preview", lambda stop: provider.fetch(values, stop))
        except RuntimeError as error:
            self._preview_pending = False
            self._set_search(busy=False, error=error_message(error))
            return
        self._preview_pending = False
        self._set_search(busy=True, error="", status=message("weather.state.updating", location=location.name))

    @Slot()
    def refresh(self) -> None:
        if self._state.busy or self._stopped:
            LOGGER.debug("忽略天气刷新：busy=%s，stopped=%s", self._state.busy, self._stopped)
            return
        if self.tasks.is_active("weather.fetch"):
            self._pending = True
            return
        self._pending = False
        values = self.configuration.get("weather")
        if self._current_location is None:
            self._set(busy=False, error="", status=message("weather.state.waiting_location"))
            return
        values.update(location_name=self._current_location.name, latitude=self._current_location.latitude,
                      longitude=self._current_location.longitude)
        provider = self.providers.get(values["provider"])
        try:
            self._fetch_generation = self.tasks.submit("weather.fetch", lambda stop: provider.fetch(values, stop))
            LOGGER.info("开始天气获取：来源 %s，预报 %d 天，历史 %d 天", values["provider"], values["forecast_days"], values["history_days"])
        except RuntimeError as error:
            self._set(status=error_message(error))
            return
        self._set(busy=True, error="", status=message("weather.state.updating", location=values["location_name"]))

    def cancel(self) -> None:
        self.cancel_current()
        self.cancel_search()

    def cancel_current(self) -> None:
        self._pending = False
        self.tasks.cancel("weather.fetch")

    def cancel_search(self) -> None:
        self._preview_pending = False
        self._search_generation = self._preview_generation = -1
        self.tasks.cancel("weather.search")
        self.tasks.cancel("weather.preview")
        self._set_search(searching=False, busy=False, status=message("weather.search.cancelled"))

    def _try_pending(self, _count: int = 0) -> None:
        if self._pending and not self._stopped and not self.tasks.is_active("weather.fetch"):
            self.refresh()
        if self._preview_pending and not self._stopped and not self.tasks.is_active("weather.preview"):
            self._fetch_preview()

    @Slot(str)
    def _configured(self, module: str) -> None:
        if module != "weather":
            return
        updated = self.configuration.get("weather")
        previous = self._values
        self._values = updated
        if all(updated[key] == previous.get(key) for key in updated if key != "search_query"):
            return
        self._configure_timer()
        if not updated["auto_refresh"]:
            self._pending = False
        LOGGER.info("天气配置已应用：自动刷新 %s，间隔 %d 分钟", updated["auto_refresh"], updated["refresh_minutes"])
        if any(updated[key] != previous[key] for key in updated if key not in ("search_query", "refresh_minutes", "auto_refresh")):
            self.cancel()
            self._fetch_generation = self._search_generation = self._preview_generation = -1
            self._set(report=None, busy=False, error="", status=message("weather.state.settings_changed"))
            self._set_search(report=None, busy=False, searching=False, error="", status=message("weather.state.settings_changed"))
            self._pending = updated["auto_refresh"]
            self._preview_pending = self._preview_location is not None
            QTimer.singleShot(0, self._try_pending)
        elif updated["auto_refresh"] and not previous["auto_refresh"]:
            self._pending = True
            QTimer.singleShot(0, self._try_pending)

    def _configure_timer(self) -> None:
        self._timer.setInterval(self._values["refresh_minutes"] * 60000)
        self._timer.start() if self._values["auto_refresh"] else self._timer.stop()

    @Slot(str, int, object, object, bool)
    def _completed(self, key: str, generation: int, result: object, error: str, cancelled: bool) -> None:
        if key == "weather.search" and generation == self._search_generation:
            LOGGER.info("地点搜索结束：状态 %s，结果数 %d", "取消" if cancelled else ("失败" if error else "成功"), len(result or ()))
            self._set_search(searching=False, locations=() if error or cancelled else result,
                      status=message("weather.search.cancelled") if cancelled else (message("weather.search.choose") if result else message("weather.search.empty")), error="" if cancelled else error)
        elif key == "weather.preview" and generation == self._preview_generation:
            if cancelled:
                self._set_search(busy=False, status=message("weather.state.cancelled"))
            elif error:
                self._set_search(busy=False, error=error, status=message("weather.state.failed_cached") if self._search_state.report else message("weather.state.failed"))
            else:
                self._set_search(busy=False, report=result, error="", status=message("weather.state.updated"))
        elif key == "weather.fetch" and generation == self._fetch_generation:
            if cancelled:
                LOGGER.info(message("weather.state.cancelled"))
                self._set(busy=False, status=message("weather.state.cancelled"))
            elif error:
                LOGGER.warning("天气更新失败，保留旧结果=%s；原因见后台任务错误日志", self._state.report is not None)
                self._set(busy=False, error=error, status=message("weather.state.failed_cached") if self._state.report else message("weather.state.failed"))
                self.alert.emit(message("weather.error.fetch", detail=error))
            else:
                self._set(busy=False, report=result, error="", status=message("weather.state.updated"))
                LOGGER.info("天气更新完成：小时 %d 条，每日 %d 条，历史 %d 条", len(result.hourly), len(result.daily), len(result.history))
        elif key in ("weather.search", "weather.fetch", "weather.preview"):
            LOGGER.debug("丢弃过期天气请求结果：%s，代次 %d", key, generation)

    def stop(self) -> None:
        LOGGER.info("天气模块停止周期刷新")
        self._stopped = True
        self._timer.stop()
        self.cancel()
