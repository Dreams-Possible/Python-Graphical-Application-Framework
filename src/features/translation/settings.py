"""翻译设置注册：提供商按各自协议配置，凭据输入默认隐藏。"""
from src.shared.configuration import SettingField as Field, SettingsSection

PROVIDERS = ("mymemory", "google", "baidu", "youdao", "libre")

SECTION = SettingsSection("translation", "settings.translation.title", "settings.translation.description", (
    Field("provider", "settings.translation.provider", "choice", choices=tuple((key, "translation.provider." + key) for key in PROVIDERS)),
    Field("timeout_seconds", "settings.translation.timeout", "int", 2, 60),
    Field("mymemory_url", "settings.translation.endpoint"),
    Field("google_url", "settings.translation.endpoint"),
    Field("google_key", "settings.translation.api_key", "secret"),
    Field("baidu_url", "settings.translation.endpoint"),
    Field("baidu_app_id", "settings.translation.app_id", "optional_text"),
    Field("baidu_secret", "settings.translation.app_secret", "secret"),
    Field("youdao_url", "settings.translation.endpoint"),
    Field("youdao_app_id", "settings.translation.app_id", "optional_text"),
    Field("youdao_secret", "settings.translation.app_secret", "secret"),
    Field("libre_url", "settings.translation.endpoint"),
    Field("libre_key", "settings.translation.optional_key", "secret"),
))
