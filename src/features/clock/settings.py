from src.shared.configuration import SettingField as Field, SettingsSection


def migrate_settings(version: int, values: dict) -> dict:
    """只迁移旧版本的默认公共服务器，保留自定义服务器与端口。"""
    if not isinstance(values, dict):
        raise ValueError("时钟配置值必须是对象")
    if version < 2 and values.get("server") == "pool.ntp.org" and values.get("port", 123) == 123:
        values["server"] = "ntp.aliyun.com"
    return values


SECTION = SettingsSection("clock", "时钟", "网络校准只影响应用中的时间显示。", (
    Field("server", "NTP 服务器", hint="主机名或 IP，不包含协议头"),
    Field("port", "服务器端口", "int", 1, 65535),
    Field("timeout_seconds", "网络超时（秒）", "int", 2, 30),
    Field("sync_minutes", "自动同步间隔（分钟）", "int", 1, 1440),
    Field("auto_sync", "自动同步", "bool"),
    Field("display_timezone", "显示时区", "choice", choices=(("local", "当前位置优先 / 系统时区"), ("utc", "UTC"))),
    Field("show_seconds", "显示秒", "bool"),
), migrate=migrate_settings)
