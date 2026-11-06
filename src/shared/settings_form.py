"""共享设置条纹行：布局、条件显隐与可见行配色统一管理。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QGridLayout, QLabel
from src.shared.ui_metrics import UI


class SettingsForm(QVBoxLayout):
    def __init__(self, parent):
        super().__init__(parent)
        self.setContentsMargins(0, 0, 0, 0)
        self.setSpacing(0)
        self.rows = []
        self.addStretch()

    def addRow(self, *widgets):
        row = QWidget()
        row.setObjectName("SettingsRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        note = len(widgets) == 1 and isinstance(widgets[0], QLabel)
        row.setMinimumHeight(UI.settings_note_height if note else UI.settings_row_height)
        grid = QGridLayout(row)
        grid.setContentsMargins(UI.settings_row_padding, UI.settings_row_padding_y,
                                UI.settings_row_padding, UI.settings_row_padding_y)
        grid.setHorizontalSpacing(UI.settings_column_gap)
        if len(widgets) == 2:
            label, editor = widgets
            label.setWordWrap(True)
            label.setBuddy(editor)
            grid.addWidget(label, 0, 0)
            grid.addWidget(editor, 0, 1)
            grid.setColumnStretch(0, 2)
            grid.setColumnStretch(1, 3)
        else:
            grid.addWidget(widgets[0], 0, 0)
        self.rows.append((row, widgets, True))
        self.insertWidget(self.count() - 1, row)
        self._stripes()

    def setRowVisible(self, widget, visible):
        for i, (row, widgets, _) in enumerate(self.rows):
            if widget in widgets:
                row.setVisible(visible)
                self.rows[i] = (row, widgets, visible)
                break
        self._stripes()

    def isRowVisible(self, widget):
        return next((visible for _, widgets, visible in self.rows if widget in widgets), False)

    def _stripes(self):
        index = 0
        for row, _, visible in self.rows:
            if visible:
                row.setProperty("alternate", bool(index % 2))
                row.style().unpolish(row)
                row.style().polish(row)
                index += 1
