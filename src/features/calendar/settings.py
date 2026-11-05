"""节假日来源配置。"""
from src.shared.configuration import SettingField as Field, SettingsSection

SECTION = SettingsSection("calendar", "settings.calendar.title", "settings.calendar.description", (
    Field("holiday_url", "settings.calendar.holiday_url.label"),
    Field("international_url", "settings.calendar.international_url.label"),
    Field("timeout_seconds", "settings.calendar.timeout_seconds.label", "int", 2, 30),
))
