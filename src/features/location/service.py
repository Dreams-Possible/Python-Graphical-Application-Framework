"""按公网出口 IP 获取大致位置，不采集 GPS，不持久化原始响应。"""

from dataclasses import dataclass
import logging
import math
from threading import Event

from PySide6.QtCore import QObject, QTimer, QTimeZone, Signal

from src.shared.configuration import SettingField as Field, SettingsSection
from src.shared.http import get_json

LOGGER = logging.getLogger("workbench.location")

SECTION = SettingsSection("location", "当前位置", "启用后，启动及保存定位设置时根据公网 IP 获取大致位置。服务会看到公网 IP；代理可能导致位置偏差。失败时保留天气配置，时钟回退系统时区。", (
    Field("enabled", "启用网络定位", "bool"),
    Field("use_for_clock", "时钟使用当前位置时区", "bool"),
    Field("use_for_weather", "天气使用当前位置", "bool"),
    Field("endpoint", "定位服务（ipwho.is 兼容协议）"),
    Field("timeout_seconds", "网络超时（秒）", "int", 2, 30),
))


@dataclass(frozen=True)
class LocationFix:
    name: str
    latitude: float
    longitude: float
    timezone: str


def parse_location(document: dict) -> LocationFix:
    if document.get("success") is not True:
        raise ValueError("网络定位服务未返回有效位置")
    latitude, longitude = document.get("latitude"), document.get("longitude")
    for value, limit in ((latitude, 90), (longitude, 180)):
        if type(value) not in (int, float) or not math.isfinite(value) or not -limit <= value <= limit:
            raise ValueError("定位响应经纬度无效")
    zone = document.get("timezone")
    zone_id = zone.get("id") if isinstance(zone, dict) else None
    if not isinstance(zone_id, str) or not QTimeZone(zone_id.encode("utf-8")).isValid():
        raise ValueError("定位响应时区无效或当前系统不支持")
    names = [document.get(key) for key in ("city", "region", "country")]
    name = " / ".join(dict.fromkeys(value for value in names if isinstance(value, str) and value.strip()))
    if not name:
        raise ValueError("定位响应缺少地点名称")
    return LocationFix(name, latitude, longitude, zone_id)


def locate(values: dict, stop: Event) -> LocationFix:
    document = get_json(values["endpoint"], {"fields": "success,city,region,country,latitude,longitude,timezone"}, values["timeout_seconds"], stop)
    return parse_location(document)


class LocationService(QObject):
    updated = Signal(object)
    started = Signal()

    def __init__(self, configuration, tasks) -> None:
        super().__init__()
        self.configuration, self.tasks = configuration, tasks
        self._generation = -1
        self._pending = False
        self._stopped = False
        configuration.changed.connect(self._configured)
        tasks.completed.connect(self._completed)
        tasks.activity_changed.connect(self._try_pending)

    def refresh(self) -> None:
        if self._stopped:
            return
        values = self.configuration.get("location")
        if not values["enabled"] or not (values["use_for_clock"] or values["use_for_weather"]):
            LOGGER.info("当前位置自动应用未启用，使用原有配置")
            self.updated.emit(None)
            return
        if self.tasks.is_active("location.lookup"):
            self._pending = True
            return
        self._pending = False
        LOGGER.info("开始网络定位：只请求大致位置与时区，不记录 IP、坐标或响应正文")
        self.started.emit()
        self._generation = self.tasks.submit("location.lookup", lambda stop: locate(values, stop))

    def _configured(self, module: str) -> None:
        if module != "location":
            return
        self.tasks.cancel("location.lookup")
        self._generation = -1
        self._pending = True
        LOGGER.info("定位配置已应用，旧请求结果失效")
        QTimer.singleShot(0, self._try_pending)

    def _try_pending(self, _count=0) -> None:
        if self._pending and not self._stopped and not self.tasks.is_active("location.lookup"):
            self._pending = False
            self.refresh()

    def _completed(self, key, generation, result, error, cancelled) -> None:
        if key != "location.lookup":
            return
        if generation != self._generation or self._stopped:
            LOGGER.debug("丢弃过期定位结果：代次 %d", generation)
            return
        if error or cancelled:
            LOGGER.warning("网络定位%s，回退已有天气位置和系统时区", "取消" if cancelled else "失败")
            self.updated.emit(None)
        else:
            LOGGER.info("网络定位成功，准备应用天气位置和时区")
            self.updated.emit(result)

    def stop(self) -> None:
        self._stopped = True
        self._pending = False
        self.tasks.cancel("location.lookup")
        LOGGER.info("当前位置模块停止")
