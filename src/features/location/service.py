"""按公网出口 IP 获取大致位置，不采集 GPS，不持久化原始响应。"""

from dataclasses import dataclass
import logging
import math
from threading import Event

from PySide6.QtCore import QObject, QTimer, QTimeZone, Signal

from src.shared.configuration import SettingField as Field, SettingsSection
from src.shared.http import get_json

LOGGER = logging.getLogger("workbench.location")

SECTION = SettingsSection("location", "当前位置", "独立于天气城市。网络模式按请求出口 IP 定位，代理可能改变结果；手动模式可搜索城市后保存。日历始终使用此位置的国家。", (
    Field("enabled", "启用当前位置", "bool"),
    Field("mode", "位置来源", "choice", choices=(("network", "网络定位（出口 IP）"), ("manual", "手动选择位置"))),
    Field("use_for_clock", "时钟使用当前位置时区", "bool"),
    Field("manual_name", "手动地点名称"),
    Field("manual_country", "国家／地区代码", hint="ISO 两位代码，例如 CN、JP、US；选择搜索结果后自动填写"),
    Field("manual_latitude", "纬度", "float", -90, 90),
    Field("manual_longitude", "经度", "float", -180, 180),
    Field("manual_timezone", "时区", hint="例如 Asia/Shanghai；选择搜索结果后自动填写"),
    Field("endpoint", "网络定位接口（ipwho.is）"),
    Field("geocoding_url", "手动地点搜索接口（Open-Meteo）"),
    Field("timeout_seconds", "网络超时（秒）", "int", 2, 30),
))


@dataclass(frozen=True)
class LocationFix:
    name: str
    latitude: float
    longitude: float
    timezone: str
    country_code: str = ""


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
    code = document.get("country_code", "")
    if code and (not isinstance(code, str) or len(code) != 2 or not code.isascii() or not code.isalpha()):
        raise ValueError("国家代码无效")
    return LocationFix(name, latitude, longitude, zone_id, code.upper())


def locate(values: dict, stop: Event) -> LocationFix:
    document = get_json(values["endpoint"], {"fields": "success,city,region,country,country_code,latitude,longitude,timezone"}, values["timeout_seconds"], stop)
    return parse_location(document)


def manual_location(values):
    fix = parse_location({"success": True, "city": values["manual_name"],
        "country_code": values["manual_country"].strip().upper(),
        "latitude": values["manual_latitude"], "longitude": values["manual_longitude"],
        "timezone": {"id": values["manual_timezone"].strip()}})
    if not fix.country_code:
        raise ValueError("请选择包含国家代码的地点")
    return fix


def search_places(query, values, stop):
    document = get_json(values["geocoding_url"], {"name": query, "count": 10, "language": "zh", "format": "json"}, values["timeout_seconds"], stop)
    results = []
    for item in document.get("results", []):
        try:
            results.append(parse_location({"success": True, "city": item.get("name"),
                "region": item.get("admin1"), "country": item.get("country"),
                "country_code": item.get("country_code"), "latitude": item.get("latitude"),
                "longitude": item.get("longitude"), "timezone": {"id": item.get("timezone")}}))
        except ValueError:
            continue
    return tuple(results)


class LocationService(QObject):
    updated = Signal(object)
    started = Signal()
    status_changed = Signal(str)
    search_finished = Signal(object, str)

    def __init__(self, configuration, tasks) -> None:
        super().__init__()
        self.configuration, self.tasks = configuration, tasks
        self.current = None
        self.status = "尚未确定当前位置"
        self._search_generation = -1
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
        if not values["enabled"]:
            LOGGER.info("当前位置自动应用未启用，使用原有配置")
            self._publish(None, "当前位置已停用")
            return
        if values.get("mode", "network") == "manual":
            try:
                self._publish(manual_location(values), "手动位置")
            except ValueError as error:
                self._publish(None, str(error))
            return
        if self.tasks.is_active("location.lookup"):
            self._pending = True
            return
        self._pending = False
        LOGGER.info("开始网络定位：只请求大致位置与时区，不记录 IP、坐标或响应正文")
        self._publish(None, "正在通过请求出口 IP 定位…")
        self.started.emit()
        try:
            self._generation = self.tasks.submit("location.lookup", lambda stop: locate(values, stop))
        except RuntimeError as error:
            self._publish(None, str(error))

    def _configured(self, module: str) -> None:
        if module != "location":
            return
        self.tasks.cancel("location.lookup")
        self._generation = -1
        self._pending = True
        self._publish(None, "位置配置已更新，正在应用…")
        LOGGER.info("定位配置已应用，旧请求结果失效")
        QTimer.singleShot(0, self._try_pending)

    def _try_pending(self, _count=0) -> None:
        if self._pending and not self._stopped and not self.tasks.is_active("location.lookup"):
            self._pending = False
            self.refresh()

    def _completed(self, key, generation, result, error, cancelled) -> None:
        if key == "location.search" and generation == self._search_generation and not self._stopped:
            self.search_finished.emit(result or (), error or ("已取消" if cancelled else ""))
            return
        if key != "location.lookup":
            return
        if generation != self._generation or self._stopped:
            LOGGER.debug("丢弃过期定位结果：代次 %d", generation)
            return
        if error or cancelled:
            LOGGER.warning("网络定位%s，当前位置不可用，时钟回退系统时区", "取消" if cancelled else "失败")
            self._publish(None, "网络定位失败，请重试或选择手动位置")
        else:
            LOGGER.info("网络定位成功，准备发布独立当前位置")
            self._publish(result, "网络位置（出口 IP）")

    def _publish(self, fix, message):
        self.current = fix
        self.status = message + (f"：{fix.name} · {fix.country_code} · {fix.timezone}" if fix else "")
        self.status_changed.emit(self.status)
        self.updated.emit(fix)

    def search(self, query):
        if not query.strip():
            self.search_finished.emit((), "请输入地点名称")
            return
        values = self.configuration.get("location")
        try:
            self._search_generation = self.tasks.submit("location.search", lambda stop: search_places(query.strip(), values, stop))
        except RuntimeError as error:
            self.search_finished.emit((), str(error))

    def stop(self) -> None:
        self._stopped = True
        self._pending = False
        self.tasks.cancel("location.lookup")
        self.tasks.cancel("location.search")
        LOGGER.info("当前位置模块停止")
