"""可随应用调色板重绘的品牌图标，复用现有日出 SVG。"""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget
from src.shared.paths import resource_path


class BrandMark(QWidget):
    def __init__(self, texts, parent=None, size=40):
        super().__init__(parent)
        self.setFixedSize(size, size)
        texts.bind_text(self, "app.brand_accessible", setter="setAccessibleName")
        self.source = resource_path("icons/sunrise.svg").read_text(encoding="utf-8")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.Highlight))
        painter.drawRoundedRect(QRectF(self.rect()), self.width() * 0.3, self.height() * 0.3)
        color = self.palette().color(QPalette.ColorRole.Link).name()
        renderer = QSvgRenderer(QByteArray(self.source.replace("currentColor", color).encode()))
        renderer.render(painter, QRectF(self.width() * 0.2, self.height() * 0.2, self.width() * 0.6, self.height() * 0.6))
        painter.end()
