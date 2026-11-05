"""页面共用标题与只读数据表。"""

from PySide6.QtWidgets import QPushButton, QAbstractItemView, QComboBox, QHeaderView, QLabel, QListView, QStyle, QStyledItemDelegate, QStyleOptionViewItem, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from src.shared.ui_metrics import UI


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


def page_layout(page: QWidget, title: str, subtitle: str, texts=None) -> QVBoxLayout:
    layout = QVBoxLayout(page)
    layout.setContentsMargins(UI.page_margin_x, UI.page_margin_y, UI.page_margin_x, UI.page_margin_y)
    layout.setSpacing(UI.page_spacing)
    heading = QLabel(title)
    if texts:
        texts.bind_text(heading, title)
    heading.setObjectName("PageTitle")
    hint = QLabel(subtitle)
    if texts:
        texts.bind_text(hint, subtitle)
    hint.setObjectName("Muted")
    hint.setWordWrap(True)
    header = QVBoxLayout()
    header.setSpacing(UI.heading_spacing)
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


def text_button(texts, key, **parameters):
    button = QPushButton()
    texts.bind_text(button, key, **parameters)
    return button


def text_label(texts, key, name="", **parameters):
    label = plain_label(name=name)
    texts.bind_text(label, key, **parameters)
    return label
