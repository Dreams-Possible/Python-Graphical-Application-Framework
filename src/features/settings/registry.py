"""只注册共享应用设置，功能模块自行提供各自设置定义。"""

from src.shared.configuration import SettingField as Field, SettingsRegistry, SettingsSection


def register_application(registry: SettingsRegistry) -> None:
    registry.register(SettingsSection("appearance", "外观", "保存后立即切换主题。跟随系统在系统未提供偏好时使用浅色。", (
        Field("theme", "主题", "choice", choices=(("system", "跟随系统"), ("light", "Daylight · 浅色"), ("dark", "Nightfall · 深色"))),
    )))
    registry.register(SettingsSection("app", "应用", "窗口尺寸和启动页面在下次启动时使用。", (
        Field("initial_page", "启动页面", "choice", choices=(("clock", "时钟"), ("weather", "天气"), ("logs", "日志"), ("settings", "设置"))),
        Field("window_width", "窗口宽度", "int", 960, 3840),
        Field("window_height", "窗口高度", "int", 680, 2160),
    )))
    registry.register(SettingsSection("logging", "日志", "日志级别决定文件记录范围，查看器筛选不改变文件内容。", (
        Field("level", "记录等级", "choice", choices=(("DEBUG", "DEBUG"), ("INFO", "INFO"), ("WARNING", "WARNING"), ("ERROR", "ERROR"))),
        Field("maximum_lines", "视图最多保留行数", "int", 100, 10000),
        Field("flush_ms", "界面批量刷新间隔（毫秒）", "int", 200, 2000),
        Field("keep_files", "保留最近日志文件数", "int", 1, 1000),
    )))
