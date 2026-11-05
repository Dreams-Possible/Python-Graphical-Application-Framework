"""节假日来源配置。"""
from src.shared.configuration import SettingField as Field, SettingsSection

SECTION = SettingsSection("calendar", "日历", "节假日跟随独立当前位置的国家。中国大陆含补班；其他地区显示国家级公共假日（不含地方专属假日）。网络失败保留对应国家缓存。", (
    Field("holiday_url", "年度 JSON 地址（包含 {year}）"),
    Field("international_url", "国际公共假日地址（包含 {year}/{country}）"),
    Field("timeout_seconds", "请求超时（秒）", "int", 2, 30),
))
