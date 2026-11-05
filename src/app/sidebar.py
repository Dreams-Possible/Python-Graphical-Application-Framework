"""侧栏列表绘制：收起时只隐藏文字，图标始终保持相同坐标。"""
from PySide6.QtCore import QRect, Qt, Signal
from PySide6.QtGui import QIcon, QPalette
from PySide6.QtWidgets import QListWidget, QStyledItemDelegate, QStyleOptionViewItem, QStyle

from src.shared.ui_metrics import UI


class SidebarList(QListWidget):
    repeatedClicked = Signal()

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        self._repeat_item = item if event.button() == Qt.MouseButton.LeftButton and item is not None and item.isSelected() else None
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.itemAt(event.position().toPoint()) is not getattr(self, "_repeat_item", None):
            self._repeat_item = None
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        repeat = getattr(self, "_repeat_item", None)
        self._repeat_item = None
        same = event.button() == Qt.MouseButton.LeftButton and repeat is not None and self.itemAt(event.position().toPoint()) is repeat
        super().mouseReleaseEvent(event)
        if same:
            self.repeatedClicked.emit()


class SidebarDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        styled = QStyleOptionViewItem(option)
        self.initStyleOption(styled, index)
        icon, text = QIcon(styled.icon), styled.text
        selected = bool(styled.state & QStyle.StateFlag.State_Selected)
        styled.state &= ~QStyle.StateFlag.State_HasFocus
        styled.icon = QIcon()
        styled.text = ""
        style = styled.widget.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, styled, painter, styled.widget)
        icon.paint(painter, QRect(option.rect.x() + UI.navigation_icon_inset, option.rect.y() + (UI.navigation_height - UI.navigation_icon) // 2, UI.navigation_icon, UI.navigation_icon),
                   Qt.AlignmentFlag.AlignCenter, QIcon.Mode.Normal, QIcon.State.On if selected else QIcon.State.Off)
        painter.save()
        painter.setFont(styled.font)
        painter.setPen(styled.palette.color(QPalette.ColorRole.HighlightedText if selected else QPalette.ColorRole.Text))
        text_rect = option.rect.adjusted(UI.navigation_text_inset, 0, -UI.navigation_icon_inset, -UI.navigation_gap)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         styled.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, max(0, text_rect.width())))
        painter.restore()
