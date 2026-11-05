"""公共 UI 尺寸：布局和主题样式共享，单位为 Qt 逻辑像素。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class UiMetrics:
    navigation_height: int = 48
    navigation_gap: int = 6
    navigation_icon: int = 20
    sidebar_collapse_height_ratio: int = 3
    sidebar_margin_x: int = 8
    sidebar_margin_y: int = 10
    splitter_width: int = 4
    title_height: int = 38
    window_button_width: int = 44
    page_margin_x: int = 20
    page_margin_y: int = 14
    page_spacing: int = 10
    heading_spacing: int = 4
    settings_categories_width: int = 168
    about_width: int = 460
    about_height: int = 310
    about_brand_size: int = 64
    about_margin: int = 32

    @property
    def navigation_row_height(self):
        return self.navigation_height + self.navigation_gap

    @property
    def navigation_icon_inset(self):
        return (self.navigation_height - self.navigation_icon) // 2

    @property
    def navigation_text_inset(self):
        return self.navigation_icon_inset + self.navigation_icon + self.navigation_gap

    @property
    def sidebar_collapsed_width(self):
        return self.navigation_height + 2 * self.sidebar_margin_x

    @property
    def sidebar_collapse_threshold(self):
        return self.navigation_height * self.sidebar_collapse_height_ratio


UI = UiMetrics()
