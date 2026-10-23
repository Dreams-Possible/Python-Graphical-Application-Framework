"""应用级主题：语义颜色、Qt 调色板及统一控件样式。"""

import logging
from string import Template

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from src.shared.paths import resource_path

LOGGER = logging.getLogger("workbench.theme")

PALETTES = {
    "light": dict(background="#EDF2F7", surface="#FFFFFF", alternate="#F6F8FC",
                  text="#19283B", muted="#63758B", border="#D4DFEC", accent="#285FE8",
                  selected="#E5EDFF", hover="#F0F4FC", success="#167C66", warning="#956014",
                  error="#BD3448", error_surface="#FFF0F1", disabled="#8A98AA", handle="#B6C5D8",
                  button_text="#FFFFFF"),
    "dark": dict(background="#151C28", surface="#1E2939", alternate="#243145",
                 text="#E7EDF6", muted="#A6B6CA", border="#35475F", accent="#8BB0FF",
                 selected="#30466C", hover="#29384E", success="#6BD4B3", warning="#E9BD70",
                 error="#FF98A7", error_surface="#492D3A", disabled="#7A8AA0", handle="#506580",
                 button_text="#15223D"),
}

STYLE = Template("""
* { font-family: 'Noto Sans CJK SC', 'Microsoft YaHei', 'PingFang SC', sans-serif;
    font-size: 14px; color: $text; }
QMainWindow, QDialog, QMessageBox { background: $background; }
QWidget#Sidebar { background: $surface; border-right: 1px solid $border; }
QLabel { background: transparent; }
QLabel#Brand { font-size: 21px; font-weight: 700; color: $accent; padding: 12px 4px; }
QLabel#PageTitle { font-size: 26px; font-weight: 600; }
QLabel#SectionTitle { font-size: 17px; font-weight: 600; }
QLabel#Muted { color: $muted; font-size: 12px; }
QLabel#Status { color: $success; font-weight: 600; }
QLabel#Status[failed='true'], QLabel#Error { color: $error; }
QLabel#Error { background: $error_surface; padding: 10px; border-radius: 8px; }
QLabel#ClockDigits { font-family: 'SFMono-Regular', 'Cascadia Mono', 'DejaVu Sans Mono', monospace;
    font-size: 64px; font-weight: 500; color: $accent; }
QLabel#Temperature { font-size: 38px; font-weight: 600; color: $accent; }
QFrame#Card, QFrame#ClockCard { background: $surface; border: 1px solid $border; border-radius: 14px; }
QPushButton { background: $surface; border: 1px solid $border; border-radius: 8px; padding: 9px 14px; }
QPushButton:hover { background: $hover; border-color: $accent; }
QPushButton:pressed { background: $selected; }
QPushButton:disabled { color: $disabled; background: $alternate; border-color: $border; }
QPushButton:focus { border-color: $accent; }
QPushButton#Primary { background: $accent; color: $button_text; border-color: $accent; }
QPushButton#Primary:hover { background: $selected; color: $text; }
QPushButton#Primary:disabled { background: $border; color: $disabled; border-color: $border; }
QPushButton#Navigation { text-align: left; border: 1px solid transparent; background: transparent; padding: 13px 16px; }
QPushButton#Navigation:hover { background: $hover; }
QPushButton#Navigation:checked { color: $accent; background: $selected; font-weight: 600; }
QPushButton#Navigation:focus { border-color: $accent; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: $surface; color: $text;
    border: 1px solid $border; border-radius: 8px; padding: 8px 12px; min-height: 22px;
    selection-background-color: $selected; selection-color: $text; }
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus { border-color: $accent; }
QSpinBox, QDoubleSpinBox { padding-right: 38px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 28px; height: 19px; margin-top: 1px; margin-right: 1px;
    background: $alternate; border: 0; border-left: 1px solid $border;
    border-bottom: 1px solid $border; border-top-right-radius: 7px; }
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 28px; height: 19px; margin-bottom: 1px; margin-right: 1px;
    background: $alternate; border: 0; border-left: 1px solid $border;
    border-bottom-right-radius: 7px; }
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover { background: $hover; }
QSpinBox::up-button:pressed, QSpinBox::down-button:pressed,
QDoubleSpinBox::up-button:pressed, QDoubleSpinBox::down-button:pressed { background: $selected; }
QSpinBox::up-button:off, QSpinBox::down-button:off,
QDoubleSpinBox::up-button:off, QDoubleSpinBox::down-button:off { background: $background; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow { image: url("$up"); width: 10px; height: 6px; }
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow { image: url("$chevron"); width: 10px; height: 6px; }
QComboBox { padding-right: 34px; }
QComboBox:hover { border-color: $accent; }
QComboBox::drop-down { subcontrol-origin: padding; subcontrol-position: top right;
    width: 28px; border: 0; border-left: 1px solid $border; }
QComboBox::down-arrow { image: url("$chevron"); width: 12px; height: 8px; }
QLineEdit:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QComboBox:disabled {
    color: $disabled; background: $alternate; }
QComboBox QAbstractItemView { background: $surface; color: $text; border: 1px solid $border;
    padding: 5px; outline: 0; selection-background-color: $selected; selection-color: $accent; }
QComboBox QAbstractItemView::item { min-height: 30px; padding: 3px 12px; border-radius: 5px; }
QComboBox QAbstractItemView::item:hover { background: $hover; }
QComboBox QAbstractItemView::item:selected { background: $selected; color: $accent; }
QCheckBox { spacing: 8px; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid $muted; border-radius: 4px; background: $surface; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url("$check"); }
QCheckBox:focus { color: $accent; }
QTableWidget { background: $surface; alternate-background-color: $alternate; gridline-color: $border;
    border: 1px solid $border; border-radius: 8px; selection-background-color: $selected; selection-color: $text; }
QHeaderView::section { background: $alternate; color: $muted; border: 0;
    border-bottom: 1px solid $border; padding: 9px; font-weight: 600; }
QTableCornerButton::section { background: $alternate; border: 0; }
QTabWidget::pane { border: 0; }
QTabBar::tab { background: $background; color: $muted; padding: 10px 16px; border-bottom: 2px solid transparent; }
QTabBar::tab:selected { color: $accent; border-bottom: 2px solid $accent; }
QTextEdit#LogConsole { background: $surface; color: $text; border: 1px solid $border;
    border-radius: 10px; padding: 12px; selection-background-color: $selected; selection-color: $text;
    font-family: 'Cascadia Mono', 'SFMono-Regular', 'DejaVu Sans Mono', monospace; font-size: 12px; }
QListWidget#SettingsCategories { background: transparent; border: 0; outline: 0; }
QListWidget#SettingsCategories::item { min-height: 24px; padding: 10px 14px;
    margin: 3px 0; border: 1px solid transparent; border-radius: 8px; }
QListWidget#SettingsCategories::item:hover { background: $hover; }
QListWidget#SettingsCategories::item:selected { background: $selected; color: $accent; font-weight: 600; }
QListWidget#SettingsCategories:focus::item:selected { border-color: $accent; }
QScrollArea { border: 0; background: transparent; }
QScrollArea > QWidget > QWidget { background: $background; }
QScrollBar:vertical { background: $background; width: 10px; margin: 0; }
QScrollBar:horizontal { background: $background; height: 10px; margin: 0; }
QScrollBar::handle { background: $handle; border-radius: 4px; min-width: 24px; min-height: 24px; }
QScrollBar::handle:hover { background: $muted; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QToolTip { background: $surface; color: $text; border: 1px solid $border; padding: 8px; }
""")


def effective_theme(mode: str, system_dark: bool) -> str:
    if mode not in ("system", "light", "dark"):
        raise ValueError("未知主题模式")
    return ("dark" if system_dark else "light") if mode == "system" else mode


class ThemeManager(QObject):
    changed = Signal()

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self.application = application
        self.mode = "system"
        self.current = ""
        self.configuration = None
        application.styleHints().colorSchemeChanged.connect(self._system_changed)
        self.apply()

    @property
    def colors(self) -> dict:
        return PALETTES[self.current]

    def bind(self, configuration) -> None:
        self.configuration = configuration
        configuration.changed.connect(self._configured)
        self._configured("appearance")

    def _configured(self, module: str) -> None:
        if module == "appearance":
            self.mode = self.configuration.get("appearance")["theme"]
            self.apply()

    def _system_changed(self, _scheme) -> None:
        if self.mode == "system":
            self.apply()

    def apply(self) -> None:
        dark = self.application.styleHints().colorScheme() == Qt.ColorScheme.Dark
        name = effective_theme(self.mode, dark)
        if name == self.current:
            return
        self.current = name
        colors = self.colors
        palette = QPalette()
        roles = {"Window": "background", "WindowText": "text", "Base": "surface",
                 "AlternateBase": "alternate", "Text": "text", "Button": "surface",
                 "ButtonText": "text", "Highlight": "selected", "HighlightedText": "text",
                 "ToolTipBase": "surface", "ToolTipText": "text", "PlaceholderText": "muted",
                 "Link": "accent", "LinkVisited": "accent"}
        for role, token in roles.items():
            palette.setColor(getattr(QPalette.ColorRole, role), QColor(colors[token]))
        for role in (QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText, QPalette.ColorRole.WindowText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(colors["disabled"]))
        self.application.setPalette(palette)
        icons = {key: resource_path(f"icons/{key}-{self.current}.svg").as_posix()
                 for key in ("chevron", "check", "up")}
        self.application.setStyleSheet(STYLE.substitute(colors, **icons))
        LOGGER.info("应用主题：%s（配置 %s）", name, self.mode)
        self.changed.emit()
