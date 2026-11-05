"""天气提供者输出与页面共享的不可变数据。"""

from dataclasses import dataclass
from datetime import datetime
from src.shared.messages import Message


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class ForecastPoint:
    when: datetime
    weather_code: int | None
    temperature: float | None = None
    apparent: float | None = None
    humidity: float | None = None
    precipitation_probability: float | None = None
    precipitation: float | None = None
    wind: float | None = None
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class WeatherReport:
    location: str
    temperature: float | None
    weather_code: int | None
    humidity: float | None
    wind: float | None
    observed_at: datetime
    timezone: str
    hourly: tuple[ForecastPoint, ...]
    daily: tuple[ForecastPoint, ...]
    history: tuple[ForecastPoint, ...]
    source: str


@dataclass(frozen=True)
class WeatherState:
    report: WeatherReport | None = None
    locations: tuple[Location, ...] = ()
    status: Message | str = Message("weather.state.choose")
    busy: bool = False
    searching: bool = False
    error: Message | str = ""
