"""页面共用标题与只读数据表。"""

from PySide6.QtWidgets import QAbstractItemView, QComboBox, QHeaderView, QLabel, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import Qt


class NavigationDelegate(QStyledItemDelegate):
    """由整行选中态与控件边框表达焦点，不画原生文字细框。"""

    def paint(self, painter, option, index) -> None:
        styled = QStyleOptionViewItem(option)
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        super().paint(painter, styled, index)


def choice_box() -> QComboBox:
    """使用 Qt 默认列表、委托和弹层交互。"""
    combo = QComboBox()
    combo.setMinimumWidth(140)
    combo.setMaxVisibleItems(12)
    return combo


def page_layout(page: QWidget, title: str, subtitle: str) -> QVBoxLayout:
    layout = QVBoxLayout(page)
    layout.setContentsMargins(28, 24, 28, 24)
    layout.setSpacing(16)
    heading = QLabel(title)
    heading.setObjectName("PageTitle")
    hint = QLabel(subtitle)
    hint.setObjectName("Muted")
    hint.setWordWrap(True)
    header = QVBoxLayout()
    header.setSpacing(4)
    header.addWidget(heading)
    header.addWidget(hint)
    layout.addLayout(header)
    return layout


def data_table(headers: tuple[str, ...]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setItemDelegate(NavigationDelegate(table))
    table.setHorizontalHeaderLabels(headers)
    table.verticalHeader().hide()
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.setWordWrap(False)
    return table


def populate(table: QTableWidget, rows: tuple[tuple[str, ...], ...]) -> None:
    table.setUpdatesEnabled(False)
    try:
        table.setRowCount(len(rows))
        for row_index, values in enumerate(rows):
            for column, text in enumerate(values):
                item = QTableWidgetItem(str(text))
                item.setToolTip(str(text))
                table.setItem(row_index, column, item)
    finally:
        table.setUpdatesEnabled(True)


def plain_label(text: str = "", name: str = "") -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label
