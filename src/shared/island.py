"""模块内浮岛导航：页面横向排列，由 Qt 属性动画平移切换。"""
from src.shared.widgets import text_button
from src.shared.gestures import SwipePages
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QFrame, QPushButton, QButtonGroup, QHBoxLayout, QVBoxLayout, QGraphicsDropShadowEffect


class IslandPages(SwipePages):
    def __init__(self, pages, parent=None, floating=False, texts=None):
        super().__init__([page for title, page in pages], parent)
        self.floating = floating
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0 if floating else 8)
        layout.setSpacing(18)
        island = QFrame(self)
        self.island = island
        island.setObjectName("ModuleIsland")
        if texts:
            texts.bind_text(island, "common.swipe_pages_hint", setter="setToolTip")
        row = QHBoxLayout(island)
        row.setContentsMargins(5, 5, 5, 5)
        row.setSpacing(4)
        group = QButtonGroup(self)
        self.buttons = []
        for index, (title, page) in enumerate(pages):
            button = text_button(texts, title) if texts else QPushButton(title)
            button.setObjectName("IslandTab")
            button.setCheckable(True)
            group.addButton(button)
            button.clicked.connect(lambda checked=False, target=index: self.select(target))
            row.addWidget(button)
            self.buttons.append(button)
        self.buttons[0].setChecked(True)
        layout.addWidget(self.viewport, 1)
        if floating:
            # 仅胶囊接收鼠标事件，周围区域仍由下方内容处理滚动和点击。
            shadow = QGraphicsDropShadowEffect(island)
            shadow.setBlurRadius(22)
            shadow.setOffset(0, 4)
            shadow.setColor(QColor(0, 0, 0, 45))
            island.setGraphicsEffect(shadow)
        else:
            layout.addWidget(island, 0, Qt.AlignmentFlag.AlignHCenter)
        self.currentChanged.connect(self._sync_buttons)
        island.installEventFilter(self)

    def _sync_buttons(self, index):
        self.buttons[index].setChecked(True)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "island", None) and event.type() == QEvent.Type.LayoutRequest:
            self._position_island()
        return super().eventFilter(watched, event)

    def _resize_pages(self):
        super()._resize_pages()
        self._position_island()

    def _position_island(self):
        if getattr(self, "floating", False) and hasattr(self, "island"):
            self.island.adjustSize()
            self.island.move(max(0, (self.width() - self.island.width()) // 2), max(0, self.height() - self.island.height() - 16))
            self.island.raise_()
