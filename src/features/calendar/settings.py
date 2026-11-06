"""节假日来源配置。"""
from src.shared.configuration import SettingField as Field, SettingsSection

def migrate_calendar_settings(version, values):
    old_default = "https://{language}.wikipedia.org/api/rest_v1/feed/onthisday/events/{month}/{day}"
    if version < 2 and values.get("history_url") == old_default:
        values["history_url"] = old_default.replace("/events/", "/selected/")
        if values.get("history_limit") == 20:
            values["history_limit"] = 5
    if version < 3 and values.get("history_limit") == 5:
        values["history_limit"] = 10
    if version < 4:
        old = values.pop("history_preload_days", None)
        values.setdefault("history_preload_before", old if old is not None else 1)
        values.setdefault("history_preload_after", old if old is not None else 2)
    return values


SECTION = SettingsSection("calendar", "settings.calendar.title", "settings.calendar.description", (
    Field("holiday_url", "settings.calendar.holiday_url.label"),
    Field("international_url", "settings.calendar.international_url.label"),
    Field("history_enabled", "settings.calendar.history_enabled.label", "bool"),
    Field("history_limit", "settings.calendar.history_limit.label", "int", 1, 100),
    Field("history_preload", "settings.calendar.history_preload.label", "bool", hint_key="settings.calendar.history_preload.hint"),
    Field("history_preload_before", "settings.calendar.history_preload_before.label", "int", 0, 30),
    Field("history_preload_after", "settings.calendar.history_preload_after.label", "int", 0, 30),
    Field("history_preload_minutes", "settings.calendar.history_preload_minutes.label", "int", 5, 1440),
    Field("history_url", "settings.calendar.history_url.label", hint_key="settings.calendar.history_url.hint"),
    Field("timeout_seconds", "settings.calendar.timeout_seconds.label", "int", 2, 30),
), migrate=migrate_calendar_settings)
