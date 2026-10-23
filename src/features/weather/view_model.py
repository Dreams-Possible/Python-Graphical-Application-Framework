"""冻结请求参数，隔离地点搜索和天气更新，拒绝过期结果。"""

from dataclasses import replace
import logging

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from src.features.weather.models import Location, WeatherState
from src.features.weather.providers import ProviderRegistry
from src.shared.configuration import Configuration
from src.shared.tasks import TaskRunner

LOGGER = logging.getLogger("workbench.weather")


class WeatherViewModel(QObject):
    changed = Signal(object)
    alert = Signal(str)

    def __init__(self, configuration: Configuration, tasks: TaskRunner, providers: ProviderRegistry) -> None:
        super().__init__()
        self.configuration, self.tasks, self.providers = configuration, tasks, providers
        self._state = WeatherState()
        self._fetch_generation = 0
        self._search_generation = 0
        self._values = configuration.get("weather")
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

    def search(self, query: str) -> None:
        query = query.strip()
        if not query:
            LOGGER.warning("地点搜索未执行：查询为空")
            self._set(error="请输入地点名称")
            return
        if self._state.searching:
            LOGGER.debug("忽略重复地点搜索：上一请求仍在执行")
            return
        try:
            self.configuration.update("weather", search_query=query)
            LOGGER.info("开始地点搜索（不记录搜索内容）")
            values = self.configuration.get("weather")
            provider = self.providers.get(values["provider"])
            self._search_generation = self.tasks.submit("weather.search", lambda stop: provider.search(query, values, stop))
        except (ValueError, OSError, RuntimeError) as error:
            LOGGER.warning("地点搜索无法启动：%s", type(error).__name__)
            self._set(error=str(error))
            return
        self._set(searching=True, error="", status="正在查找地点…")

    def select_location(self, index: int) -> None:
        if not 0 <= index < len(self._state.locations):
            return
        location: Location = self._state.locations[index]
        LOGGER.info("用户选择搜索结果：第 %d 项，更新天气位置配置", index + 1)
        try:
            self.configuration.update("weather", location_name=location.name, latitude=location.latitude, longitude=location.longitude)
        except (ValueError, OSError) as error:
            LOGGER.warning("地点配置更新失败：%s", type(error).__name__)
            self._set(error=str(error))
            return
        self.refresh()

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
        provider = self.providers.get(values["provider"])
        try:
            self._fetch_generation = self.tasks.submit("weather.fetch", lambda stop: provider.fetch(values, stop))
            LOGGER.info("开始天气获取：来源 %s，预报 %d 天，历史 %d 天", values["provider"], values["forecast_days"], values["history_days"])
        except RuntimeError as error:
            self._set(status=str(error))
            return
        self._set(busy=True, error="", status=f"正在更新 {values['location_name']}…")

    def cancel(self) -> None:
        self._pending = False
        self.tasks.cancel("weather.fetch")
        self.tasks.cancel("weather.search")

    def _try_pending(self, _count: int = 0) -> None:
        if self._pending and not self._stopped and not self.tasks.is_active("weather.fetch"):
            self.refresh()

    @Slot(str)
    def _configured(self, module: str) -> None:
        if module != "weather":
            return
        updated = self.configuration.get("weather")
        previous = self._values
        self._values = updated
        self._configure_timer()
        if not updated["auto_refresh"]:
            self._pending = False
        LOGGER.info("天气配置已应用：自动刷新 %s，间隔 %d 分钟", updated["auto_refresh"], updated["refresh_minutes"])
        if any(updated[key] != previous[key] for key in updated if key not in ("search_query", "refresh_minutes", "auto_refresh")):
            self.cancel()
            self._fetch_generation = self._search_generation = -1
            self._set(report=None, locations=(), busy=False, searching=False, error="", status="天气设置已更新，请刷新获取当前地点数据")
            self._pending = updated["auto_refresh"]
            QTimer.singleShot(0, self._try_pending)
        elif updated["auto_refresh"] and not previous["auto_refresh"]:
            self._pending = True
            QTimer.singleShot(0, self._try_pending)

    def _configure_timer(self) -> None:
        self._timer.setInterval(self._values["refresh_minutes"] * 60000)
        self._timer.start() if self._values["auto_refresh"] else self._timer.stop()

    @Slot(str, int, object, str, bool)
    def _completed(self, key: str, generation: int, result: object, error: str, cancelled: bool) -> None:
        if key == "weather.search" and generation == self._search_generation:
            LOGGER.info("地点搜索结束：状态 %s，结果数 %d", "取消" if cancelled else ("失败" if error else "成功"), len(result or ()))
            self._set(searching=False, locations=() if error or cancelled else result,
                      status="地点搜索已取消" if cancelled else ("选择下方地点以更新天气" if result else "没有找到匹配地点"), error="" if cancelled else error)
        elif key == "weather.fetch" and generation == self._fetch_generation:
            if cancelled:
                LOGGER.info("天气更新已取消")
                self._set(busy=False, status="天气更新已取消")
            elif error:
                LOGGER.warning("天气更新失败，保留旧结果=%s；原因见后台任务错误日志", self._state.report is not None)
                self._set(busy=False, error=error, status="更新失败，保留上次结果" if self._state.report else "天气获取失败")
                self.alert.emit(f"天气获取失败：{error}")
            else:
                self._set(busy=False, report=result, error="", status="已更新 · 下方时间均为地点当地时间")
                LOGGER.info("天气更新完成：小时 %d 条，每日 %d 条，历史 %d 条", len(result.hourly), len(result.daily), len(result.history))
        elif key in ("weather.search", "weather.fetch"):
            LOGGER.debug("丢弃过期天气请求结果：%s，代次 %d", key, generation)

    def stop(self) -> None:
        LOGGER.info("天气模块停止周期刷新")
        self._stopped = True
        self._timer.stop()
        self.cancel()
