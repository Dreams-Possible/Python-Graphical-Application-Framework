from src.shared.configuration import SettingField as Field, SettingsSection


def section(provider_choices: tuple[tuple[str, str], ...]) -> SettingsSection:
    return SettingsSection("weather", "天气", "服务地址需符合选定来源的接口协议。地点也可在天气页搜索选择。", (
        Field("provider", "天气来源", "choice", choices=provider_choices),
        Field("forecast_url", "天气接口地址"),
        Field("geocoding_url", "地点搜索地址"),
        Field("location_name", "当前地点名称"),
        Field("latitude", "纬度", "float", -90, 90),
        Field("longitude", "经度", "float", -180, 180),
        Field("forecast_days", "每日预报天数（含今天）", "int", 10, 16),
        Field("history_days", "历史天数", "int", 0, 7, hint="归档预报，并非逐站实测"),
        Field("refresh_minutes", "自动更新间隔（分钟）", "int", 5, 1440),
        Field("timeout_seconds", "网络超时（秒）", "int", 2, 30),
        Field("auto_refresh", "自动更新天气", "bool"),
        Field("search_query", "上次地点搜索"),
    ))
