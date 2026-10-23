"""天气来源协议与公开 Open-Meteo 适配器。"""

from datetime import datetime, timedelta, timezone
import math
from threading import Event
from typing import Protocol

from src.features.weather.models import Location, WeatherReport
from src.shared.http import get_json


class WeatherProvider(Protocol):
    key: str
    title: str

    def search(self, query: str, settings: dict, cancelled: Event) -> tuple[Location, ...]: ...
    def fetch(self, settings: dict, cancelled: Event) -> WeatherReport: ...


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, WeatherProvider] = {}

    def register(self, provider: WeatherProvider) -> None:
        if provider.key in self._providers:
            raise ValueError("天气来源 ID 重复")
        self._providers[provider.key] = provider

    @property
    def choices(self) -> tuple[tuple[str, str], ...]:
        return tuple((key, provider.title) for key, provider in self._providers.items())

    def get(self, key: str) -> WeatherProvider:
        return self._providers[key]


def number(value: object, suffix: str = "") -> str:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        return "—"
    return f"{value:g}{suffix}"


def condition(code: object) -> str:
    descriptions = {
        0: "晴", 1: "大部晴朗", 2: "局部多云", 3: "阴", 45: "雾", 48: "冻雾",
        51: "小毛毛雨", 53: "毛毛雨", 55: "强毛毛雨", 56: "冻毛毛雨", 57: "强冻毛毛雨",
        61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "强冻雨",
        71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒", 80: "小阵雨", 81: "阵雨",
        82: "强阵雨", 85: "阵雪", 86: "强阵雪", 95: "雷暴", 96: "雷暴伴冰雹", 99: "强雷暴伴冰雹",
    }
    return descriptions.get(code, "暂无天气描述")


def parse_report(document: dict, settings: dict) -> WeatherReport:
    current = document.get("current")
    hourly = document.get("hourly")
    daily = document.get("daily")
    if not all(isinstance(value, dict) for value in (current, hourly, daily)):
        raise ValueError("天气响应缺少当前、小时或每日数据")
    offset = document.get("utc_offset_seconds", 0)
    now = current.get("time")
    if not isinstance(now, (int, float)) or not isinstance(offset, (int, float)):
        raise ValueError("天气响应的时间格式无效")

    def date(seconds, pattern: str) -> str:
        return (datetime.fromtimestamp(seconds, timezone.utc) + timedelta(seconds=offset)).strftime(pattern)

    def values(section: dict, key: str, index: int):
        column = section.get(key, [])
        return column[index] if isinstance(column, list) and index < len(column) else None

    def timestamps(section: dict) -> list:
        times = section.get("time")
        if not isinstance(times, list) or not times or any(type(value) not in (int, float) for value in times):
            raise ValueError("天气时间序列为空或格式无效")
        return times

    start_hour = ((now + offset) // 3600) * 3600 - offset
    hours = []
    for index, timestamp in enumerate(timestamps(hourly)):
        if timestamp < start_hour or timestamp >= start_hour + 24 * 3600:
            continue
        hours.append((
            date(timestamp, "%m-%d %H:%M"), condition(values(hourly, "weather_code", index)),
            number(values(hourly, "temperature_2m", index), " °C"),
            number(values(hourly, "apparent_temperature", index), " °C"),
            number(values(hourly, "relative_humidity_2m", index), "%"),
            number(values(hourly, "precipitation_probability", index), "%"),
            number(values(hourly, "precipitation", index), " mm"),
            number(values(hourly, "wind_speed_10m", index), " km/h"),
        ))
    days, history = [], []
    today = date(now, "%Y-%m-%d")
    for index, timestamp in enumerate(timestamps(daily)):
        day = date(timestamp, "%Y-%m-%d")
        row = (
            day, condition(values(daily, "weather_code", index)),
            number(values(daily, "temperature_2m_min", index), " °C"),
            number(values(daily, "temperature_2m_max", index), " °C"),
            number(values(daily, "precipitation_probability_max", index), "%"),
            number(values(daily, "precipitation_sum", index), " mm"),
            number(values(daily, "wind_speed_10m_max", index), " km/h"),
        )
        (history if day < today else days).append(row)
    return WeatherReport(
        settings["location_name"], number(current.get("temperature_2m"), " °C"),
        condition(current.get("weather_code")), number(current.get("relative_humidity_2m"), "%"),
        number(current.get("wind_speed_10m"), " km/h"), date(now, "%Y-%m-%d %H:%M"),
        str(document.get("timezone", "当地时间")), tuple(hours), tuple(days), tuple(history),
        "Open-Meteo · 天气模型数据 · CC BY 4.0",
    )


class OpenMeteoProvider:
    key = "open_meteo"
    title = "Open-Meteo / 兼容服务"

    def search(self, query: str, settings: dict, cancelled: Event) -> tuple[Location, ...]:
        document = get_json(settings["geocoding_url"], {"name": query, "count": 10, "language": "zh", "format": "json"}, settings["timeout_seconds"], cancelled)
        result = []
        for item in document.get("results", []):
            label = " / ".join(str(item[key]) for key in ("name", "admin1", "country") if item.get(key))
            latitude, longitude = float(item["latitude"]), float(item["longitude"])
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ValueError("地点接口返回无效坐标")
            result.append(Location(label, latitude, longitude))
        return tuple(result)

    def fetch(self, settings: dict, cancelled: Event) -> WeatherReport:
        document = get_json(settings["forecast_url"], {
            "latitude": settings["latitude"], "longitude": settings["longitude"],
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "hourly": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation_probability,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum,precipitation_probability_max,wind_speed_10m_max",
            "forecast_days": settings["forecast_days"], "past_days": settings["history_days"],
            "timezone": "auto", "timeformat": "unixtime",
        }, settings["timeout_seconds"], cancelled)
        return parse_report(document, settings)
