"""天气来源协议与公开 Open-Meteo 适配器。"""

from src.shared.errors import ui_error

from datetime import datetime, timedelta, timezone
import math
from threading import Event
from typing import Protocol

from src.features.weather.models import Location, WeatherReport, ForecastPoint
from src.shared.http import get_json


class WeatherProvider(Protocol):
    key: str
    title_key: str

    def search(self, query: str, settings: dict, cancelled: Event) -> tuple[Location, ...]: ...
    def fetch(self, settings: dict, cancelled: Event) -> WeatherReport: ...


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, WeatherProvider] = {}

    def register(self, provider: WeatherProvider) -> None:
        if provider.key in self._providers:
            raise ui_error(ValueError, "errors.provider_id")
        self._providers[provider.key] = provider

    @property
    def choices(self) -> tuple[tuple[str, str], ...]:
        return tuple((key, provider.title_key) for key, provider in self._providers.items())

    def get(self, key: str) -> WeatherProvider:
        return self._providers[key]


def numeric(value):
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def weather_code(value):
    return value if type(value) is int else None


def parse_report(document: dict, settings: dict) -> WeatherReport:
    current = document.get("current")
    hourly = document.get("hourly")
    daily = document.get("daily")
    if not all(isinstance(value, dict) for value in (current, hourly, daily)):
        raise ui_error(ValueError, "errors.weather_response")
    offset = document.get("utc_offset_seconds", 0)
    now = current.get("time")
    if not isinstance(now, (int, float)) or not isinstance(offset, (int, float)):
        raise ui_error(ValueError, "errors.weather_time")

    def local_time(seconds):
        return datetime.fromtimestamp(seconds, timezone(timedelta(seconds=offset)))

    def values(section: dict, key: str, index: int):
        column = section.get(key, [])
        return column[index] if isinstance(column, list) and index < len(column) else None

    def timestamps(section: dict) -> list:
        times = section.get("time")
        if not isinstance(times, list) or not times or any(type(value) not in (int, float) for value in times):
            raise ui_error(ValueError, "errors.weather_series")
        return times

    start_hour = ((now + offset) // 3600) * 3600 - offset
    hours = []
    for index, timestamp in enumerate(timestamps(hourly)):
        if timestamp < start_hour or timestamp >= start_hour + 24 * 3600:
            continue
        hours.append(ForecastPoint(
            when=local_time(timestamp), weather_code=weather_code(values(hourly, "weather_code", index)),
            temperature=numeric(values(hourly, "temperature_2m", index)),
            apparent=numeric(values(hourly, "apparent_temperature", index)),
            humidity=numeric(values(hourly, "relative_humidity_2m", index)),
            precipitation_probability=numeric(values(hourly, "precipitation_probability", index)),
            precipitation=numeric(values(hourly, "precipitation", index)),
            wind=numeric(values(hourly, "wind_speed_10m", index)),
        ))
    days, history = [], []
    today = local_time(now).date()
    for index, timestamp in enumerate(timestamps(daily)):
        day = local_time(timestamp)
        point = ForecastPoint(
            when=day, weather_code=weather_code(values(daily, "weather_code", index)),
            minimum=numeric(values(daily, "temperature_2m_min", index)),
            maximum=numeric(values(daily, "temperature_2m_max", index)),
            precipitation_probability=numeric(values(daily, "precipitation_probability_max", index)),
            precipitation=numeric(values(daily, "precipitation_sum", index)),
            wind=numeric(values(daily, "wind_speed_10m_max", index)),
        )
        (history if day.date() < today else days).append(point)
    return WeatherReport(
        settings["location_name"], numeric(current.get("temperature_2m")),
        weather_code(current.get("weather_code")), numeric(current.get("relative_humidity_2m")),
        numeric(current.get("wind_speed_10m")), local_time(now),
        str(document.get("timezone", "")), tuple(hours), tuple(days), tuple(history),
        "Open-Meteo / CC BY 4.0",
    )


class OpenMeteoProvider:
    key = "open_meteo"
    title_key = "settings.weather.provider.open_meteo"

    def search(self, query: str, settings: dict, cancelled: Event) -> tuple[Location, ...]:
        document = get_json(settings["geocoding_url"], {"name": query, "count": 10, "language": "zh", "format": "json"}, settings["timeout_seconds"], cancelled)
        result = []
        for item in document.get("results", []):
            label = " / ".join(str(item[key]) for key in ("name", "admin1", "country") if item.get(key))
            latitude, longitude = float(item["latitude"]), float(item["longitude"])
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ui_error(ValueError, "errors.search_coordinates")
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
