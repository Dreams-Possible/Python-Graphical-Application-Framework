"""可随应用调色板重绘的品牌图标，复用现有日出 SVG。"""
from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QPainter, QPalette
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget
from src.shared.paths import resource_path


class BrandMark(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(40, 40)
        self.setAccessibleName("Daylight 日出标志")
        self.source = resource_path("icons/sunrise.svg").read_text(encoding="utf-8")

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self.palette().color(QPalette.ColorRole.Highlight))
        painter.drawRoundedRect(QRectF(self.rect()), 12, 12)
        color = self.palette().color(QPalette.ColorRole.Link).name()
        renderer = QSvgRenderer(QByteArray(self.source.replace("currentColor", color).encode()))
        renderer.render(painter, QRectF(8, 8, 24, 24))
        painter.end()
