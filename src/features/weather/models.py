"""天气提供者输出与页面共享的不可变数据。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class WeatherReport:
    location: str
    temperature: str
    condition: str
    humidity: str
    wind: str
    observed_at: str
    timezone: str
    hourly: tuple[tuple[str, ...], ...]
    daily: tuple[tuple[str, ...], ...]
    history: tuple[tuple[str, ...], ...]
    source: str


@dataclass(frozen=True)
class WeatherState:
    report: WeatherReport | None = None
    locations: tuple[Location, ...] = ()
    status: str = "选择地点后获取天气"
    busy: bool = False
    searching: bool = False
    error: str = ""
