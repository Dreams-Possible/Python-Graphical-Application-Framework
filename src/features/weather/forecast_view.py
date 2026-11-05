"""天气趋势绘制：共用调色板的线条图标、小时曲线和每日温度区间。"""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import QWidget
from src.features.weather.presentation import condition as condition_text, forecast_row



def daily_title(value, texts, current=False):
    weekday = texts.weekday(value.isoweekday(), short=True)
    if current:
        return texts.get("weather.today_weekday", weekday=weekday)
    return texts.get("weather.date_weekday", date=texts.short_date(value), weekday=weekday)


def weather_icon(painter, rect, condition, color):
    """按天气代码绘制矢量图标，未知天气使用问号而非晴天。"""
    painter.save()
    painter.translate(rect.x(), rect.y())
    painter.scale(rect.width() / 40, rect.height() / 40)
    painter.setPen(QPen(color, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    if condition == 2:
        # 只画露在云层外的太阳弧和光芒，轮廓之间不交叉。
        painter.drawArc(QRectF(6, 5, 17, 17), 0, 220 * 16)
        for angle in (0, 45, 90, 135, 180):
            radians = math.radians(angle)
            painter.drawLine(QPointF(14.5 + 11 * math.cos(radians), 13.5 - 11 * math.sin(radians)), QPointF(14.5 + 13 * math.cos(radians), 13.5 - 13 * math.sin(radians)))
    elif condition in (0, 1):
        painter.drawEllipse(QRectF(10, 9, 15, 15))
        for angle in range(0, 360, 45):
            radians = math.radians(angle)
            painter.drawLine(QPointF(17.5 + 11 * math.cos(radians), 16.5 + 11 * math.sin(radians)), QPointF(17.5 + 14 * math.cos(radians), 16.5 + 14 * math.sin(radians)))
    cloud = condition in (2, 3, 45, 48, 51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99)
    if cloud:
        path = QPainterPath(QPointF(12, 30))
        path.cubicTo(3, 30, 3, 19, 12, 19)
        path.cubicTo(14, 11, 27, 12, 29, 22)
        path.cubicTo(38, 19, 40, 30, 31, 30)
        path.closeSubpath()
        painter.drawPath(path)
        if condition in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
            for x in (13, 22, 31):
                painter.drawLine(QPointF(x, 33), QPointF(x - 2, 37))
        elif condition in (71, 73, 75, 77, 85, 86):
            for x in (13, 23, 33):
                painter.drawEllipse(QRectF(x - 1, 34, 2, 2))
        elif condition in (95, 96, 99):
            painter.drawPolyline([QPointF(23, 30), QPointF(18, 35), QPointF(24, 35), QPointF(20, 40)])
        elif condition in (45, 48):
            painter.drawLine(QPointF(8, 33), QPointF(33, 33))
            painter.drawLine(QPointF(12, 37), QPointF(29, 37))
    elif condition not in (0, 1):
        painter.drawText(QRectF(0, 0, 40, 40), Qt.AlignmentFlag.AlignCenter, "?")
    painter.restore()


class WeatherSymbol(QWidget):
    def __init__(self, texts):
        super().__init__()
        self.texts = texts
        texts.changed.connect(self.retranslate)
        self.condition = None
        self.setFixedSize(64, 64)

    def set_condition(self, condition):
        self.condition = condition
        self.retranslate()
        self.update()

    def retranslate(self):
        self.setAccessibleName(condition_text(self.texts, self.condition))
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        weather_icon(painter, QRectF(4, 4, 56, 56), self.condition, self.palette().color(QPalette.ColorRole.Accent))


class ForecastGraphic(QWidget):
    """统一横向趋势列；仅当前小时和今天使用主题高亮背景。"""
    COLUMN_WIDTH = 104
    EXPANDED_WIDTH = 280

    def __init__(self, texts, hourly=False):
        super().__init__()
        self.texts = texts
        self.hourly = hourly
        texts.changed.connect(self.retranslate)
        self.rows = ()
        self._hovered_index = -1
        self.current_index = -1
        self.selected_index = -1
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.retranslate()
        self.set_rows(())

    def set_rows(self, rows, current_key=""):
        self.selected_index = -1
        self.rows = rows
        self.current_index = next((index for index, row in enumerate(rows) if (row.when.strftime("%m-%d %H:%M") if self.hourly else row.when.date().isoformat()) == current_key), -1)
        self.retranslate()
        self._resize_columns()
        self.setFixedHeight(278 if self.hourly else 320)
        self.update()

    def retranslate(self):
        self.setAccessibleName(self.texts.get("weather.hours_accessible" if self.hourly else "weather.days_accessible"))
        self.setToolTip("\n".join(forecast_row(self.rows[self._hovered_index], self.hourly, self.texts)) if 0 <= self._hovered_index < len(self.rows) else "")
        self.setAccessibleDescription("\n".join(" | ".join(forecast_row(point, self.hourly, self.texts)) for point in self.rows) or self.texts.get("weather.no_data"))
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
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.texts.get("weather.no_data"))
            return
        values = [point.temperature if self.hourly else point.minimum for point in self.rows]
        if not self.hourly:
            values += [point.maximum for point in self.rows]
        valid = [value for value in values if value is not None]
        low, high = (min(valid), max(valid)) if valid else (0, 1)
        span = max(1, high - low)
        align = Qt.AlignmentFlag.AlignCenter
        previous_high = previous_low = None
        for index, point_data in enumerate(self.rows):
            row = forecast_row(point_data, self.hourly, self.texts)
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
                fields = ((self.texts.get("weather.apparent"), row[3]), (self.texts.get("weather.humidity"), row[4]), (self.texts.get("weather.probability"), row[5]), (self.texts.get("weather.precipitation"), row[6]), (self.texts.get("weather.wind"), row[7])) if self.hourly else ((self.texts.get("weather.minimum"), row[2]), (self.texts.get("weather.maximum"), row[3]), (self.texts.get("weather.probability"), row[4]), (self.texts.get("weather.precipitation"), row[5]), (self.texts.get("weather.max_wind"), row[6]))
                for detail_index, (label, value) in enumerate(fields):
                    y = 48 + detail_index * 43
                    painter.setPen(muted)
                    painter.drawText(QRectF(detail_left + 4, y, 148, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, label)
                    painter.setPen(text)
                    painter.drawText(QRectF(detail_left + 4, y + 18, 148, 22), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, value)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(accent if index == self.current_index else muted)
            title = (self.texts.get("weather.current_hour") if index == self.current_index else row[0]) if self.hourly else daily_title(point_data.when.date(), self.texts, index == self.current_index)
            painter.drawText(QRectF(x - 48, 8, 96, 22), align, title)
            weather_icon(painter, QRectF(x - 18, 38, 36, 36), point_data.weather_code, accent)
            painter.setPen(text)
            painter.drawText(QRectF(x - 48, 76, 96, 24), align, painter.fontMetrics().elidedText(row[1], Qt.TextElideMode.ElideRight, 96))
            # 所有列共用同一温度刻度，缺失值断开曲线。
            high_value = point_data.temperature if self.hourly else point_data.maximum
            low_value = point_data.minimum if not self.hourly else None
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
            painter.drawText(QRectF(x - 48, 174, 96, 25), align, row[2] if self.hourly else self.texts.get("weather.high_value", value=row[3]))
            if not self.hourly:
                painter.setPen(muted)
                painter.drawText(QRectF(x - 48, 204, 96, 25), align, self.texts.get("weather.low_value", value=row[2]))
            offset = 0 if self.hourly else 36
            painter.setPen(muted)
            painter.drawText(QRectF(x - 48, 206 + offset, 96, 22), align, self.texts.get("weather.rain_value", value=row[5 if self.hourly else 4]))
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

    def mouseMoveEvent(self, event):
        index = self._index_at(event.position())
        self._hovered_index = index
        self.setToolTip("\n".join(forecast_row(self.rows[index], self.hourly, self.texts)) if index >= 0 else "")
        super().mouseMoveEvent(event)

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
