"""时钟页面唯一状态所有者；每秒走时与周期联网分别调度。"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import time

from PySide6.QtCore import QDateTime, QObject, Qt, QTimer, QTimeZone, Signal, Slot

from src.features.clock.service import TimeSample, query_time
from src.shared.configuration import Configuration
from src.shared.tasks import TaskRunner

LOGGER = logging.getLogger("workbench.clock")


@dataclass(frozen=True)
class ClockState:
    time_text: str
    date_text: str
    timezone_text: str
    status: str
    detail: str
    busy: bool
    failed: bool


class ClockViewModel(QObject):
    changed = Signal(object)
    alert = Signal(str)

    def __init__(self, configuration: Configuration, tasks: TaskRunner) -> None:
        super().__init__()
        self._configuration, self._tasks = configuration, tasks
        self._sample: TimeSample | None = None
        self._location_timezone = ""
        self._generation = 0
        self._busy = False
        self._active = False
        self._pending = False
        self._stopped = False
        self._error = ""
        self._last_sync = "尚未同步"
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._publish)
        self._sync = QTimer(self)
        self._sync.timeout.connect(self.synchronize)
        configuration.changed.connect(self._configure)
        tasks.completed.connect(self._completed)
        tasks.activity_changed.connect(self._try_pending)
        self._configure("clock")

    @property
    def state(self) -> ClockState:
        values = self._configuration.get("clock")
        seconds = time.time() if self._sample is None else self._sample.utc_seconds + time.monotonic() - self._sample.monotonic_seconds
        current = datetime.fromtimestamp(seconds, timezone.utc)
        if values["display_timezone"] == "local":
            zone = QTimeZone(self._location_timezone.encode("utf-8"))
            if self._location_timezone and zone.isValid():
                offset = zone.offsetFromUtc(QDateTime.fromSecsSinceEpoch(int(seconds), Qt.TimeSpec.UTC))
                current = current.astimezone(timezone(timedelta(seconds=offset), self._location_timezone))
            else:
                current = current.astimezone()
        status = "同步中" if self._busy else ("同步失败" if self._error else ("网络时间" if self._sample else "系统时间 · 未校准"))
        detail = self._error or f"服务器 {values['server']} · 最近同步 {self._last_sync}"
        if self._sample:
            detail += f" · 校准偏差 {self._sample.offset_seconds * 1000:+.0f} ms"
        return ClockState(
            current.strftime("%H:%M:%S" if values["show_seconds"] else "%H:%M"),
            current.strftime("%Y 年 %m 月 %d 日"), current.strftime("%Z · UTC%z") + (" · IP 定位" if self._location_timezone and values["display_timezone"] == "local" else ""),
            status, detail, self._busy, bool(self._error),
        )

    def set_active(self, active: bool) -> None:
        self._active = active
        self._tick.start() if active else self._tick.stop()
        if active:
            self._publish()

    def set_location_timezone(self, zone_id: str) -> None:
        self._location_timezone = zone_id
        LOGGER.info("时钟时区来源更新：%s", "网络当前位置" if zone_id else "系统时区（UTC 选项保持优先）")
        self._publish()

    @Slot()
    def synchronize(self) -> None:
        if self._busy or self._stopped:
            LOGGER.debug("忽略校时请求：busy=%s，stopped=%s", self._busy, self._stopped)
            return
        if self._tasks.is_active("clock.sync"):
            self._pending = True
            return
        self._pending = False
        values = self._configuration.get("clock")
        try:
            LOGGER.info("开始网络校时，超时 %d 秒", values["timeout_seconds"])
            self._generation = self._tasks.submit("clock.sync", lambda stop: query_time(values, stop))
        except RuntimeError:
            return
        self._busy, self._error = True, ""
        self._publish()

    def cancel(self) -> None:
        self._pending = False
        self._tasks.cancel("clock.sync")

    def _try_pending(self, _count: int = 0) -> None:
        if self._pending and not self._stopped and not self._tasks.is_active("clock.sync"):
            self.synchronize()

    @Slot(str)
    def _configure(self, module: str) -> None:
        if module != "clock":
            return
        self.cancel()
        self._generation = -1  # 丢弃旧设置发起的结果。
        self._busy = False
        self._sample = None
        self._error = ""
        self._last_sync = "尚未同步"
        values = self._configuration.get("clock")
        LOGGER.info("时钟配置已应用：自动同步 %s，间隔 %d 分钟，显示时区 %s", values["auto_sync"], values["sync_minutes"], values["display_timezone"])
        self._sync.setInterval(values["sync_minutes"] * 60000)
        self._sync.start() if values["auto_sync"] else self._sync.stop()
        self._pending = values["auto_sync"]
        QTimer.singleShot(0, self._try_pending)
        self._publish()

    @Slot(str, int, object, str, bool)
    def _completed(self, key: str, generation: int, result: object, error: str, cancelled: bool) -> None:
        if key != "clock.sync" or generation != self._generation:
            if key == "clock.sync":
                LOGGER.debug("丢弃旧校时结果：代次 %d，当前 %d", generation, self._generation)
            return
        self._busy = False
        if cancelled:
            LOGGER.info("网络校时已取消")
            self._error = "同步已取消，继续显示已有时间"
        elif error:
            LOGGER.warning("校时失败，保留当前时间来源；原因见后台任务错误日志")
            self._error = error
            self.alert.emit(f"时间同步失败：{error}")
        else:
            self._sample = result
            self._last_sync = datetime.now().strftime("%H:%M:%S")
            self._error = ""
            LOGGER.info("网络校时完成，偏差 %.3f 秒", result.offset_seconds)
        self._publish()

    def _publish(self) -> None:
        if self._active:
            self.changed.emit(self.state)

    def stop(self) -> None:
        LOGGER.info("时钟模块停止自动同步与走时刷新")
        self._stopped = True
        self._sync.stop()
        self._tick.stop()
        self.cancel()
