"""在应用入口集中创建并连接对象。"""

from PySide6.QtCore import QTimer
import logging

from src.features.calendar.view import CalendarView
from src.features.calendar.holidays import HolidayService
from src.features.calendar.history import HistoryRepository, HistoryService
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
from src.shared.localization import Localization
from src.features.location.service import LocationService, SECTION as LOCATION_SETTINGS

LOGGER = logging.getLogger("workbench.bootstrap")


def create_main_window(paths: UserPaths, logs: LoggingService, themes: ThemeManager, texts=None) -> ApplicationWindow:
    """只在组合根创建依赖，功能模块不自行寻找其他模块。"""
    texts = texts if texts is not None else Localization()
    providers = ProviderRegistry()
    providers.register(OpenMeteoProvider())
    registry = SettingsRegistry()
    register_application(registry)
    registry.register(CLOCK_SETTINGS)
    registry.register(weather_settings(providers.choices))
    registry.register(CALENDAR_SETTINGS)
    registry.register(LOCATION_SETTINGS)
    configuration = Configuration(SettingsRepository(paths.config, registry))
    themes.bind(configuration)
    texts.bind(configuration)
    tasks = TaskRunner()
    holidays = HolidayService(tasks, paths.cache, configuration)
    history = HistoryService(tasks, configuration, HistoryRepository(paths.cache))
    location = LocationService(configuration, tasks)
    clock = ClockViewModel(configuration, tasks)
    weather = WeatherViewModel(configuration, tasks, providers)
    log_model = LogsViewModel(logs, configuration, tasks)
    storage = StorageViewModel(StorageRepository(paths, logs.path), tasks)

    def stop_producers() -> None:
        history.stop()
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
        PageDefinition("clock", "app.navigation.clock", "◷", ClockView(clock, texts)),
        PageDefinition("weather", "app.navigation.weather", "☀", WeatherView(weather, texts)),
        PageDefinition("calendar", "app.navigation.calendar", "", CalendarView(themes, texts, holidays, history)),
        PageDefinition("logs", "app.navigation.logs", "≡", LogsView(log_model, themes, texts)),
        PageDefinition("settings", "app.navigation.settings", "⚙", SettingsView(registry, configuration, storage, texts, location)),
    ), configuration, tasks, stop_producers, texts)
    themes.bind_window(window)
    texts.bind_window(window)
    clock.alert.connect(window.notifications.report)
    weather.alert.connect(window.notifications.report)
    LOGGER.info("应用装配完成：5 个页面，%d 个配置模块", len(registry.sections))
    QTimer.singleShot(0, location.refresh)
    if configuration.get("weather")["auto_refresh"]:
        QTimer.singleShot(0, weather.refresh)
    return window
