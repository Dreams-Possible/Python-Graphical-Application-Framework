"""模块内浮岛导航：页面横向排列，由 Qt 属性动画平移切换。"""
from PySide6.QtCore import QEvent, QPoint, QPropertyAnimation, QEasingCurve, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QWidget, QFrame, QPushButton, QButtonGroup, QHBoxLayout, QVBoxLayout, QGraphicsDropShadowEffect


class IslandPages(QWidget):
    def __init__(self, pages, parent=None, floating=False):
        super().__init__(parent)
        self.floating = floating
        self.pages = [page for title, page in pages]
        self.current = 0
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0 if floating else 8)
        layout.setSpacing(18)
        island = QFrame(self)
        self.island = island
        island.setObjectName("ModuleIsland")
        row = QHBoxLayout(island)
        row.setContentsMargins(5, 5, 5, 5)
        row.setSpacing(4)
        group = QButtonGroup(self)
        self.buttons = []
        for index, (title, page) in enumerate(pages):
            button = QPushButton(title)
            button.setObjectName("IslandTab")
            button.setCheckable(True)
            group.addButton(button)
            button.clicked.connect(lambda checked=False, target=index: self.select(target))
            row.addWidget(button)
            self.buttons.append(button)
        self.buttons[0].setChecked(True)
        self.viewport = QWidget()
        self.viewport.installEventFilter(self)
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
        self.strip = QWidget(self.viewport)
        for page in self.pages:
            page.setParent(self.strip)
        self.animation = QPropertyAnimation(self.strip, b"pos", self)
        self.animation.setDuration(260)
        self.animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.animation.finished.connect(self._settled)

    def select(self, index):
        if index == self.current:
            return
        self.animation.stop()
        self.current = index
        self.buttons[index].setChecked(True)
        for page in self.pages:
            page.show()
        self.buttons[index].setFocus()
        self.animation.setStartValue(self.strip.pos())
        self.animation.setEndValue(QPoint(-index * self.viewport.width(), 0))
        self.animation.start()

    def _settled(self):
        for index, page in enumerate(self.pages):
            page.setVisible(index == self.current)

    def eventFilter(self, watched, event):
        if watched is self.viewport and event.type() == QEvent.Type.Resize and hasattr(self, "animation"):
            self._resize_pages()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_pages()

    def _resize_pages(self):
        self.animation.stop()
        width, height = self.viewport.width(), self.viewport.height()
        self.strip.resize(width * len(self.pages), height)
        for index, page in enumerate(self.pages):
            page.setGeometry(index * width, 0, width, height)
        self.strip.move(-self.current * width, 0)
        self._settled()
        if self.floating:
            self.island.adjustSize()
            self.island.move(max(0, (self.width() - self.island.width()) // 2), max(0, self.height() - self.island.height() - 16))
            self.island.raise_()
