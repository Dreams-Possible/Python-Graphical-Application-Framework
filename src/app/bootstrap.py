"""在应用入口集中创建并连接对象。"""

from PySide6.QtCore import QTimer
import logging

from src.features.calendar.view import CalendarView
from src.features.calendar.holidays import HolidayService
from src.features.calendar.settings import SECTION as CALENDAR_SETTINGS
from src.app.main_window import ApplicationWindow, PageDefinition
from src.features.clock.settings import SECTION as CLOCK_SETTINGS
from src.features.clock.view import ClockView
from src.features.clock.view_model import ClockViewModel
from src.features.weather.settings import section as weather_settings
from src.features.weather.providers import OpenMeteoProvider, ProviderRegistry
from src.features.weather.view import WeatherView
from src.features.weather.view_model import WeatherViewModel
from src.features.logs.view import LogsView
from src.features.logs.view_model import LogsViewModel
from src.features.settings.registry import register_application
from src.features.settings.storage import StorageRepository, StorageViewModel
from src.features.settings.view import SettingsView
from src.shared.configuration import Configuration, SettingsRegistry, SettingsRepository
from src.shared.logging_service import LoggingService
from src.shared.paths import UserPaths
from src.shared.tasks import TaskRunner
from src.shared.theme import ThemeManager
from src.features.location.service import LocationService, SECTION as LOCATION_SETTINGS

LOGGER = logging.getLogger("workbench.bootstrap")


def create_main_window(paths: UserPaths, logs: LoggingService, themes: ThemeManager) -> ApplicationWindow:
    """只在组合根创建依赖，功能模块不自行寻找其他模块。"""
    providers = ProviderRegistry()
    providers.register(OpenMeteoProvider())
    registry = SettingsRegistry()
    register_application(registry)
    registry.register(CLOCK_SETTINGS)
    registry.register(weather_settings(providers.choices))
    registry.register(LOCATION_SETTINGS)
    registry.register(CALENDAR_SETTINGS)
    configuration = Configuration(SettingsRepository(paths.config, registry))
    themes.bind(configuration)
    tasks = TaskRunner()
    holidays = HolidayService(tasks, paths.cache, configuration)
    location = LocationService(configuration, tasks)
    clock = ClockViewModel(configuration, tasks)
    weather = WeatherViewModel(configuration, tasks, providers)
    log_model = LogsViewModel(logs, configuration, tasks)
    storage = StorageViewModel(StorageRepository(paths, logs.path), tasks)

    def stop_producers() -> None:
        location.stop()
        clock.stop()
        weather.stop()
        log_model.stop()

    def apply_location(fix) -> None:
        values = configuration.get("location")
        clock.set_location_timezone(fix.timezone if fix and values["enabled"] and values["use_for_clock"] else "")
        holidays.set_location(fix)

    location.updated.connect(apply_location)

    window = ApplicationWindow((
        PageDefinition("clock", "时钟", "◷", ClockView(clock)),
        PageDefinition("weather", "天气", "☀", WeatherView(weather)),
        PageDefinition("calendar", "日历", "", CalendarView(themes, holidays)),
        PageDefinition("logs", "日志", "≡", LogsView(log_model, themes)),
        PageDefinition("settings", "设置", "⚙", SettingsView(registry, configuration, storage, location)),
    ), configuration, tasks, stop_producers)
    themes.bind_window(window)
    clock.alert.connect(window.notifications.report)
    weather.alert.connect(window.notifications.report)
    LOGGER.info("应用装配完成：5 个页面，%d 个配置模块", len(registry.sections))
    QTimer.singleShot(0, location.refresh)
    if configuration.get("weather")["auto_refresh"]:
        QTimer.singleShot(0, weather.refresh)
    return window
