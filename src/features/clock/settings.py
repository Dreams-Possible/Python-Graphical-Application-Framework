
from src.shared.errors import ui_error
from src.shared.configuration import SettingField as Field, SettingsSection


def migrate_settings(version: int, values: dict) -> dict:
    """只迁移旧版本的默认公共服务器，保留自定义服务器与端口。"""
    if not isinstance(values, dict):
        raise ui_error(ValueError, "errors.clock_config")
    if version < 2 and values.get("server") == "pool.ntp.org" and values.get("port", 123) == 123:
        values["server"] = "ntp.aliyun.com"
    return values


SECTION = SettingsSection("clock", "settings.clock.title", "settings.clock.description", (
    Field("server", "settings.clock.server.label", hint_key="settings.clock.server.hint"),
    Field("port", "settings.clock.port.label", "int", 1, 65535),
    Field("timeout_seconds", "settings.clock.timeout_seconds.label", "int", 2, 30),
    Field("sync_minutes", "settings.clock.sync_minutes.label", "int", 1, 1440),
    Field("auto_sync", "settings.clock.auto_sync.label", "bool"),
    Field("display_timezone", "settings.clock.display_timezone.label", "choice", choices=(("local", "settings.clock.display_timezone.local"), ("utc", "settings.clock.display_timezone.utc"))),
    Field("show_seconds", "settings.clock.show_seconds.label", "bool"),
), migrate=migrate_settings)
