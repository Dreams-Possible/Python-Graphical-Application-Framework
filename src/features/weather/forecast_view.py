"""天气趋势绘制：共用调色板的线条图标、小时曲线和每日温度区间。"""
import math
import re

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget



def temperature(value):
    match = re.match(r"^-?\d+(?:\.\d+)?", value)
    return float(match[0]) if match else None


def weather_icon(painter, rect, condition, color):
    """按天气描述绘制矢量图标，未知天气使用问号而非晴天。"""
    painter.save()
    painter.translate(rect.x(), rect.y())
    painter.scale(rect.width() / 40, rect.height() / 40)
    painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if "多云" in condition:
        # 只画露在云层外的太阳弧和光芒，轮廓之间不交叉。
        painter.drawArc(QRectF(6, 5, 17, 17), 0, 220 * 16)
        for angle in (0, 45, 90, 135, 180):
            radians = math.radians(angle)
            painter.drawLine(QPointF(14.5 + 11 * math.cos(radians), 13.5 - 11 * math.sin(radians)), QPointF(14.5 + 13 * math.cos(radians), 13.5 - 13 * math.sin(radians)))
    elif "晴" in condition:
        painter.drawEllipse(QRectF(10, 9, 15, 15))
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            painter.drawLine(QPointF(17.5 + 11 * math.cos(radians), 16.5 + 11 * math.sin(radians)), QPointF(17.5 + 14 * math.cos(radians), 16.5 + 14 * math.sin(radians)))
    cloud = any(word in condition for word in ("云", "阴", "雨", "雪", "雷", "雾", "冰雹"))
    if cloud:
        path = QPainterPath(QPointF(12, 30))
        path.cubicTo(3, 30, 3, 19, 12, 19)
        path.cubicTo(14, 11, 27, 12, 29, 22)
        path.cubicTo(38, 19, 40, 30, 31, 30)
        path.closeSubpath()
        painter.drawPath(path)
        if "雨" in condition:
            for x in (13, 22, 31):
                painter.drawLine(QPointF(x, 33), QPointF(x - 2, 37))
        elif "雪" in condition or "冰雹" in condition:
            for x in (13, 23, 33):
                painter.drawEllipse(QRectF(x - 1, 34, 2, 2))
        elif "雷" in condition:
            painter.drawPolyline([QPointF(23, 30), QPointF(18, 35), QPointF(24, 35), QPointF(20, 40)])
        elif "雾" in condition:
            painter.drawLine(QPointF(8, 33), QPointF(33, 33))
            painter.drawLine(QPointF(12, 37), QPointF(29, 37))
    elif "晴" not in condition:
        painter.drawText(QRectF(0, 0, 40, 40), Qt.AlignmentFlag.AlignCenter, "?")
    painter.restore()


class WeatherSymbol(QWidget):
    def __init__(self):
        super().__init__()
        self.condition = ""
        self.setFixedSize(64, 64)

    def set_condition(self, condition):
        self.condition = condition
        self.setAccessibleName(condition or "暂无天气")
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        weather_icon(painter, QRectF(4, 4, 56, 56), self.condition, self.palette().color(QPalette.ColorRole.Accent))


class ForecastGraphic(QWidget):
    """统一横向趋势列；仅当前小时和今天使用主题高亮背景。"""
    COLUMN_WIDTH = 104
    EXPANDED_WIDTH = 280

    def __init__(self, hourly=False):
        super().__init__()
        self.hourly = hourly
        self.rows = ()
        self.current_index = -1
        self.selected_index = -1
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("逐小时天气趋势" if hourly else "每日高低温趋势")
        self.set_rows(())

    def set_rows(self, rows, current_key=""):
        self.selected_index = -1
        self.rows = rows
        self.current_index = next((index for index, row in enumerate(rows) if row[0] == current_key), -1)
        self.setAccessibleDescription("\n".join("，".join(row) for row in rows) or "暂无数据")
        self._resize_columns()
        self.setFixedHeight(278 if self.hourly else 320)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        text = self.palette().color(QPalette.ColorRole.WindowText)
        muted = self.palette().color(QPalette.ColorRole.PlaceholderText)
        accent = self.palette().color(QPalette.ColorRole.Accent)
        minimum_color = self.palette().color(QPalette.ColorRole.PlaceholderText)
        painter.setPen(muted)
        if not self.rows:
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "暂无数据")
            return
        values = [temperature(row[2]) for row in self.rows]
        if not self.hourly:
            values += [temperature(row[3]) for row in self.rows]
        valid = [value for value in values if value is not None]
        low, high = (min(valid), max(valid)) if valid else (0, 1)
        span = max(1, high - low)
        align = Qt.AlignmentFlag.AlignCenter
        previous_high = previous_low = None
        for index, row in enumerate(self.rows):
            bounds = self._column_rect(index)
            x = bounds.left() + self.COLUMN_WIDTH / 2
            column = bounds.adjusted(4, 2, -4, -2)
            if index == self.current_index:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self.palette().color(QPalette.ColorRole.Highlight))
                painter.drawRoundedRect(column, 12, 12)
            if index == self.selected_index:
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.setPen(QPen(accent, 1.5))
                painter.drawRoundedRect(column.adjusted(1, 1, -1, -1), 12, 12)
            if index == self.selected_index:
                detail_left = bounds.left() + self.COLUMN_WIDTH + 8
                painter.setPen(self.palette().color(QPalette.ColorRole.Mid))
                painter.drawLine(QPointF(detail_left - 6, 18), QPointF(detail_left - 6, self.height() - 18))
                painter.setPen(accent)
                painter.drawText(QRectF(detail_left, 12, 156, 24), align, row[0])
                fields = (("体感", row[3]), ("湿度", row[4]), ("降水概率", row[5]), ("降水量", row[6]), ("风速", row[7])) if self.hourly else (("最低温度", row[2]), ("最高温度", row[3]), ("降水概率", row[4]), ("降水量", row[5]), ("最大风速", row[6]))
                for detail_index, (label, value) in enumerate(fields):
                    y = 48 + detail_index * 43
                    painter.setPen(muted)
                    painter.drawText(QRectF(detail_left + 4, y, 148, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
                    painter.setPen(text)
                    painter.drawText(QRectF(detail_left + 4, y + 18, 148, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(accent if index == self.current_index else muted)
            title = row[0] if self.hourly else row[0][5:]
            if index == self.current_index:
                title = "当前小时" if self.hourly else "今天"
            painter.drawText(QRectF(x - 48, 8, 96, 22), align, title)
            weather_icon(painter, QRectF(x - 18, 38, 36, 36), row[1], accent)
            painter.setPen(text)
            painter.drawText(QRectF(x - 48, 76, 96, 24), align, row[1])
            # 所有列共用同一温度刻度，缺失值断开曲线。
            high_value = temperature(row[2] if self.hourly else row[3])
            low_value = temperature(row[2]) if not self.hourly else None
            points = []
            for value, previous, color in ((high_value, previous_high, accent), (low_value, previous_low, minimum_color)):
                point = QPointF(x, 160 - (value - low) / span * 48) if value is not None else None
                if point is not None:
                    painter.setPen(QPen(color, 2))
                    if previous is not None and index - 1 != self.selected_index:
                        painter.drawLine(previous, point)
                    painter.setBrush(color)
                    painter.drawEllipse(point, 3, 3)
                points.append(point)
            previous_high, previous_low = points
            painter.setPen(text)
            painter.drawText(QRectF(x - 48, 174, 96, 25), align, row[2] if self.hourly else "最高 " + row[3])
            if not self.hourly:
                painter.setPen(muted)
                painter.drawText(QRectF(x - 48, 204, 96, 25), align, "最低 " + row[2])
            offset = 0 if self.hourly else 36
            painter.setPen(muted)
            painter.drawText(QRectF(x - 48, 206 + offset, 96, 22), align, "降水 " + row[5 if self.hourly else 4])
            painter.drawText(QRectF(x - 48, 236 + offset, 96, 22), align, row[7 if self.hourly else 6])

    def _column_rect(self, index):
        left = index * self.COLUMN_WIDTH
        if 0 <= self.selected_index < index:
            left += self.EXPANDED_WIDTH - self.COLUMN_WIDTH
        width = self.EXPANDED_WIDTH if index == self.selected_index else self.COLUMN_WIDTH
        return QRectF(left, 0, width, self.height())

    def _resize_columns(self):
        width = len(self.rows) * self.COLUMN_WIDTH
        if self.selected_index >= 0:
            width += self.EXPANDED_WIDTH - self.COLUMN_WIDTH
        self.setMinimumWidth(max(340, width))
        self.updateGeometry()
        self.update()

    def _index_at(self, position):
        if not self.rect().contains(position.toPoint()):
            return -1
        for index in range(len(self.rows)):
            if self._column_rect(index).contains(position):
                return index
        return -1

    def _toggle_details(self, index):
        self.selected_index = index if 0 <= index < len(self.rows) and index != self.selected_index else -1
        self._resize_columns()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._toggle_details(self._index_at(event.position()))
            event.accept()
        else:
            super().mousePressEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.selected_index = -1
            self._resize_columns()
            event.accept()
        elif self.rows and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self._toggle_details(self.selected_index if self.selected_index >= 0 else max(0, self.current_index))
            event.accept()
        else:
            super().keyPressEvent(event)
