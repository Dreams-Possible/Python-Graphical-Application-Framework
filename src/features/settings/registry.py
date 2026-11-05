"""只注册共享应用设置，功能模块自行提供各自设置定义。"""

from src.shared.configuration import SettingField as Field, SettingsRegistry, SettingsSection


def register_application(registry: SettingsRegistry) -> None:
    registry.register(SettingsSection("appearance", "settings.appearance.title", "settings.appearance.description", (
        Field("language", "settings.appearance.language.label", "choice", choices=(("system", "settings.appearance.language.system"), ("zh-CN", "settings.appearance.language.zh-CN"), ("en-US", "settings.appearance.language.en-US"))),
        Field("theme", "settings.appearance.theme.label", "choice", choices=(("system", "settings.appearance.theme.system"), ("light", "settings.appearance.theme.light"), ("dark", "settings.appearance.theme.dark"))),
    )))
    registry.register(SettingsSection("app", "settings.app.title", "settings.app.description", (
        Field("initial_page", "settings.app.initial_page.label", "choice", choices=(("clock", "settings.app.initial_page.clock"), ("weather", "settings.app.initial_page.weather"), ("calendar", "settings.app.initial_page.calendar"), ("logs", "settings.app.initial_page.logs"), ("settings", "settings.app.initial_page.settings"))),
        Field("window_width", "settings.app.window_width.label", "int", 960, 3840),
        Field("window_height", "settings.app.window_height.label", "int", 680, 2160),
    )))
    registry.register(SettingsSection("logging", "settings.logging.title", "settings.logging.description", (
        Field("level", "settings.logging.level.label", "choice", choices=(("DEBUG", "settings.logging.level.DEBUG"), ("INFO", "settings.logging.level.INFO"), ("WARNING", "settings.logging.level.WARNING"), ("ERROR", "settings.logging.level.ERROR"))),
        Field("maximum_lines", "settings.logging.maximum_lines.label", "int", 100, 10000),
        Field("flush_ms", "settings.logging.flush_ms.label", "int", 200, 2000),
        Field("keep_files", "settings.logging.keep_files.label", "int", 1, 1000),
    )))
