"""公共鼠标手势基类：点击、惯性滚动与跟手切页，单次手势只交给一个目标。"""
from time import monotonic

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRectF, QPropertyAnimation, QEasingCurve, Qt, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (QApplication, QAbstractButton, QAbstractItemView, QAbstractSlider,
    QAbstractSpinBox, QComboBox, QLabel, QLineEdit, QPlainTextEdit, QScrollArea, QScroller,
    QScrollerProperties, QTableWidget, QTextEdit, QWidget)
from shiboken6 import isValid
from src.shared.ui_metrics import UI


class _ClickCapture:
    def __init__(self):
        self.reset()

    def reset(self):
        self.global_origin = None
        self.local_origin = None
        self.dragged = False

    def press(self, event):
        self.global_origin = event.globalPosition()
        self.local_origin = event.position()
        self.dragged = False

    def move(self, event):
        if self.global_origin is not None and (event.globalPosition() - self.global_origin).manhattanLength() >= QApplication.startDragDistance():
            self.dragged = True

    def release(self, event, rect):
        valid = (self.global_origin is not None and not self.dragged
                 and rect.contains(event.position().toPoint())
                 and (event.globalPosition() - self.global_origin).manhattanLength() < QApplication.startDragDistance())
        origin = self.local_origin if valid else None
        self.reset()
        return origin


class DragClickWidget(QWidget):
    """仅在未发生拖动且原地释放时发布点击；业务控件自行解释点击位置。"""
    clickReleased = Signal(QPointF, QPointF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._click = _ClickCapture()

    def cancel_click(self):
        self._click.reset()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click.press(event)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._click.move(event)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        origin = self._click.release(event, self.rect())
        if origin is not None:
            self.clickReleased.emit(origin, event.position())
        event.accept()

    def hideEvent(self, event):
        self.cancel_click()
        super().hideEvent(event)


class SwipeTableWidget(QTableWidget):
    """显式允许翻页手势的表格；普通表格仍保留原生拖选。"""
    def __init__(self, rows, columns, parent=None):
        super().__init__(rows, columns, parent)
        self._click = _ClickCapture()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._click.press(event)
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.MouseButton.LeftButton:
            self._click.move(event)
            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return super().mouseReleaseEvent(event)
        origin = self._click.release(event, self.viewport().rect())
        if origin is not None:
            press = QMouseEvent(QEvent.Type.MouseButtonPress, origin, event.globalPosition(),
                                Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, event.modifiers())
            super().mousePressEvent(press)
            super().mouseReleaseEvent(event)
        event.accept()

    def mouseDoubleClickEvent(self, event):
        self._click.reset()
        press = QMouseEvent(QEvent.Type.MouseButtonPress, event.position(), event.globalPosition(),
                            event.button(), event.buttons(), event.modifiers())
        super().mousePressEvent(press)
        super().mouseDoubleClickEvent(event)

    def hideEvent(self, event):
        self._click.reset()
        super().hideEvent(event)


def _click_surfaces(widget):
    result = widget.findChildren(DragClickWidget)
    return ([widget] if isinstance(widget, DragClickWidget) else []) + result


class KineticScrollArea(QScrollArea):
    """按指定方向滚动；由公共路由器区分嵌套滚动与翻页，不抢输入控件事件。"""
    def __init__(self, axis=Qt.Orientation.Vertical, parent=None):
        super().__init__(parent)
        self.axis = axis
        self.setWidgetResizable(True)
        if axis == Qt.Orientation.Horizontal:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        else:
            self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.kinetic = QScroller.scroller(self.viewport())
        properties = self.kinetic.scrollerProperties()
        metric = QScrollerProperties.ScrollMetric
        properties.setScrollMetric(metric.MousePressEventDelay, 0)
        properties.setScrollMetric(metric.DragStartDistance, QApplication.startDragDistance() / max(1, self.kinetic.pixelPerMeter().x()))
        properties.setScrollMetric(metric.HorizontalOvershootPolicy, QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        properties.setScrollMetric(metric.VerticalOvershootPolicy, QScrollerProperties.OvershootPolicy.OvershootAlwaysOff)
        self.kinetic.setScrollerProperties(properties)
        self.kinetic.stateChanged.connect(self._scroll_state)
        self._gestures = _PointerRouter(self)

    def setWidget(self, widget):
        super().setWidget(widget)
        for target in _click_surfaces(widget):
            target.setCursor(Qt.CursorShape.OpenHandCursor)

    def _scroll_state(self, state):
        if self.widget() is None:
            return
        for target in _click_surfaces(self.widget()):
            if state in (QScroller.State.Dragging, QScroller.State.Scrolling):
                target.cancel_click()
                target.setToolTip("")
            target.setCursor(Qt.CursorShape.ClosedHandCursor if state == QScroller.State.Dragging else Qt.CursorShape.OpenHandCursor)

    def hideEvent(self, event):
        self.kinetic.stop()
        self._gestures.cancel()
        super().hideEvent(event)


class _PeriodBoundary(QWidget):
    """仅在周期过渡期间显示，覆盖边缘形成留白与主题强调边框。"""
    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.hide()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect())
        inset = UI.period_frame_inset
        inner = rect.adjusted(inset, inset, -inset, -inset)
        outer_path, inner_path = QPainterPath(), QPainterPath()
        outer_path.addRect(rect)
        inner_path.addRoundedRect(inner, UI.period_frame_radius, UI.period_frame_radius)
        painter.fillPath(outer_path.subtracted(inner_path), self.palette().color(QPalette.ColorRole.Window))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(self.palette().color(QPalette.ColorRole.Accent), UI.period_frame_width))
        painter.drawRoundedRect(inner, UI.period_frame_radius, UI.period_frame_radius)
        painter.end()


class SwipePages(QWidget):
    """跟手平移、距离／速度判定及回弹；导航外观由子类提供。"""
    currentChanged = Signal(int)

    def __init__(self, pages, parent=None):
        super().__init__(parent)
        if not pages:
            raise ValueError("SwipePages requires at least one page")
        self.pages = list(pages)
        self._boundary_frames = []
        self._persistent_boundaries = False
        self.current = 0
        self.viewport = QWidget(self)
        self.viewport.installEventFilter(self)
        self.strip = QWidget(self.viewport)
        for page in self.pages:
            page.setParent(self.strip)
        self.animation = QPropertyAnimation(self.strip, b"pos", self)
        self.animation.setDuration(UI.page_slide_ms)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.finished.connect(self._settled)
        self._gestures = _PointerRouter(self)

    def select(self, index):
        if 0 <= index < len(self.pages):
            self._gestures.cancel(settle=False)
            self._animate_to(index)

    def _animate_to(self, index):
        self.animation.stop()
        previous = self.current
        self.current = index
        for page in self.pages:
            page.show()
        self._show_boundaries(self.strip.x() != -index * self.viewport.width())
        self.animation.setStartValue(self.strip.pos())
        self.animation.setEndValue(QPoint(-index * self.viewport.width(), 0))
        if previous != index:
            self.currentChanged.emit(index)
        self.animation.start()

    def begin_swipe(self):
        self.animation.stop()
        for area in self.findChildren(KineticScrollArea):
            area.kinetic.stop()
        self._drag_start_x = self.strip.x()
        for page in self.pages:
            page.show()
        self._show_boundaries(True)

    def enable_period_boundaries(self):
        self._persistent_boundaries = True
        if not self._boundary_frames:
            self._boundary_frames = [_PeriodBoundary(self.strip) for page in self.pages]
        self._resize_pages()

    def _show_boundaries(self, visible):
        visible = visible or self._persistent_boundaries
        for index, frame in enumerate(self._boundary_frames):
            frame.setGeometry(index * self.viewport.width(), 0, self.viewport.width(), self.viewport.height())
            frame.setVisible(visible)
            if visible:
                frame.raise_()

    def move_swipe(self, distance):
        distance = max(-self.viewport.width(), min(self.viewport.width(), distance))
        if (self.current == 0 and distance > 0) or (self.current == len(self.pages) - 1 and distance < 0):
            distance *= UI.swipe_edge_resistance
        self.strip.move(round(self._drag_start_x + distance), 0)

    def end_swipe(self, distance, velocity):
        threshold = max(UI.swipe_min_distance, min(UI.swipe_max_distance, self.viewport.width() * UI.swipe_distance_ratio))
        change = abs(distance) >= threshold or (abs(distance) >= QApplication.startDragDistance() and abs(velocity) >= UI.swipe_velocity and velocity * distance > 0)
        target = self.current + (-1 if distance > 0 else 1) if change else self.current
        self._animate_to(max(0, min(len(self.pages) - 1, target)))

    def _settled(self):
        self._show_boundaries(False)
        for index, page in enumerate(self.pages):
            page.setVisible(index == self.current)

    def eventFilter(self, watched, event):
        if watched is self.viewport and event.type() == QEvent.Type.Resize and hasattr(self, "animation"):
            self._resize_pages()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.layout() is None:
            self.viewport.setGeometry(self.rect())
        self._resize_pages()

    def _resize_pages(self):
        if hasattr(self, "_gestures"):
            self._gestures.cancel(settle=False)
        self.animation.stop()
        width, height = self.viewport.width(), self.viewport.height()
        self.strip.resize(width * len(self.pages), height)
        for index, page in enumerate(self.pages):
            inset = UI.period_frame_inset + UI.period_frame_width if self._persistent_boundaries else 0
            page.setGeometry(index * width + inset, inset, max(0, width - 2 * inset), max(0, height - 2 * inset))
        self.strip.move(-self.current * width, 0)
        self._settled()

    def hideEvent(self, event):
        self._show_boundaries(False)
        if hasattr(self, "_gestures"):
            self._gestures.cancel(settle=False)
            self.animation.stop()
            self.strip.move(-self.current * self.viewport.width(), 0)
        super().hideEvent(event)


class PeriodSwipePages(SwipePages):
    """三个可复用的相邻周期视图；完成切页后回到中间槽，周期含义交给调用者。"""
    stepRequested = Signal(int)

    def __init__(self, pages, parent=None):
        self._period_ready = False
        if len(pages) != 3:
            raise ValueError("PeriodSwipePages requires previous, current and next pages")
        super().__init__(pages, parent)
        self.current = 1
        self._period_ready = True
        self.enable_period_boundaries()

    def reset_period(self):
        self._gestures.cancel(settle=False)
        self.animation.stop()
        self.current = 1
        self.strip.move(-self.viewport.width(), 0)
        super()._settled()

    def _settled(self):
        if not getattr(self, "_period_ready", False) or self.current == 1:
            return super()._settled()
        direction = self.current - 1
        self.setUpdatesEnabled(False)
        try:
            self.reset_period()
            self.stepRequested.emit(direction)
        finally:
            self.setUpdatesEnabled(True)



class _PointerRouter(QObject):
    """每个容器拥有路由器；按祖先链只让实际手势根处理一次事件。"""
    def __init__(self, owner):
        super().__init__(owner)
        self.owner = owner
        self._sending_cancel = False
        self._press = None
        self._target = None
        self._kind = None
        QApplication.instance().installEventFilter(self)

    @staticmethod
    def _chain(widget):
        chain = []
        while isinstance(widget, QWidget):
            chain.append(widget)
            widget = widget.parentWidget()
        return chain

    @staticmethod
    def _scope(chain):
        for widget in chain:
            if isinstance(widget, SwipePages):
                return widget
        areas = [widget for widget in chain if isinstance(widget, KineticScrollArea)]
        return areas[-1] if areas else None

    @staticmethod
    def _excluded(chain, owner):
        for widget in chain:
            if isinstance(widget, SwipeTableWidget):
                continue
            if isinstance(widget, (QAbstractButton, QAbstractItemView, QAbstractSlider, QAbstractSpinBox,
                                   QComboBox, QLineEdit, QTextEdit, QPlainTextEdit)):
                return True
            if isinstance(widget, QLabel) and widget.openExternalLinks():
                return True
            if widget.property("excludeSwipe"):
                return True
            if widget is owner:
                break
        return False

    def _cancel_receiver(self):
        receiver = self._receiver
        if not isValid(receiver):
            return
        if isinstance(receiver, DragClickWidget):
            receiver.cancel_click()
        else:
            outside = QPointF(-1000000, -1000000)
            event = QMouseEvent(QEvent.Type.MouseButtonRelease, outside, outside,
                                Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
            self._sending_cancel = True
            try:
                QApplication.sendEvent(receiver, event)
            finally:
                self._sending_cancel = False

    def _axis_position(self, position):
        point = QPointF(position)
        if self._target.axis == Qt.Orientation.Horizontal:
            point.setY(self._scroll_origin.y())
        else:
            point.setX(self._scroll_origin.x())
        return point

    def cancel(self, settle=True):
        if self._kind == "scroll" and isValid(self._target):
            self._target.kinetic.stop()
        elif self._kind == "page" and settle:
            self.owner._animate_to(self.owner.current)
        self._press = None
        self._target = None
        self._kind = None

    def eventFilter(self, watched, event):
        if self._sending_cancel or not isinstance(watched, QWidget):
            return False
        kind = event.type()
        if kind == QEvent.Type.WindowDeactivate and watched is self.owner.window():
            self.cancel()
            return False
        if kind not in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseMove, QEvent.Type.MouseButtonRelease):
            return False
        if not self.owner.isEnabled():
            self.cancel()
            return False
        chain = self._chain(watched)
        if self._scope(chain) is not self.owner:
            return False
        if kind == QEvent.Type.MouseButtonPress:
            if self._press is not None and event.globalPosition() == self._press and isValid(self._receiver) and watched is not self._receiver and watched.isAncestorOf(self._receiver):
                return False  # 同一次按下向父控件传播，保留原始目标与候选滚动区。
            self.cancel()
            if event.button() != Qt.MouseButton.LeftButton or self._excluded(chain, self.owner):
                return False
            self._receiver = watched
            self._press = event.globalPosition()
            self._started = monotonic()
            self._samples = [(self._started, self._press.x())]
            self._areas = [widget for widget in chain if isinstance(widget, KineticScrollArea)]
            for area in self._areas:
                area.kinetic.stop()
            return False
        if self._press is None:
            return False
        position = event.globalPosition()
        delta = position - self._press
        now = monotonic()
        if kind == QEvent.Type.MouseMove:
            if not event.buttons() & Qt.MouseButton.LeftButton:
                self.cancel()
                return False
            self._samples.append((now, position.x()))
            self._samples = [sample for sample in self._samples if now - sample[0] <= 0.15]
            if self._kind is None:
                if delta.manhattanLength() < QApplication.startDragDistance():
                    return False
                dx, dy = abs(delta.x()), abs(delta.y())
                if max(dx, dy) < min(dx, dy) * UI.swipe_axis_bias:
                    return False
                axis = Qt.Orientation.Horizontal if dx > dy else Qt.Orientation.Vertical
                self._target = next((area for area in self._areas if area.axis == axis), None)
                if self._target is not None:
                    self._kind = "scroll"
                elif axis == Qt.Orientation.Horizontal and isinstance(self.owner, SwipePages):
                    self._kind = "page"
                    self._target = self.owner
                else:
                    self._kind = "blocked"
                if self._kind != "blocked":
                    self._cancel_receiver()
                    if self._kind == "scroll":
                        origin = self._target.viewport().mapFromGlobal(self._press.toPoint())
                        self._scroll_origin = QPointF(origin)
                        self._target.kinetic.handleInput(QScroller.Input.InputPress, QPointF(origin), int(self._started * 1000))
                    else:
                        self.owner.begin_swipe()
            if self._kind == "scroll":
                local = self._target.viewport().mapFromGlobal(position.toPoint())
                self._target.kinetic.handleInput(QScroller.Input.InputMove, self._axis_position(local), int(now * 1000))
                return True
            if self._kind == "page":
                self.owner.move_swipe(delta.x())
                return True
            return False
        if event.button() != Qt.MouseButton.LeftButton:
            return False
        consumed = self._kind in ("scroll", "page")
        if self._kind == "scroll":
            local = self._target.viewport().mapFromGlobal(position.toPoint())
            self._target.kinetic.handleInput(QScroller.Input.InputRelease, self._axis_position(local), int(now * 1000))
        elif self._kind == "page":
            first = self._samples[0]
            velocity = (position.x() - first[1]) / max(0.001, now - first[0]) if now - first[0] <= 0.2 else 0
            self.owner.end_swipe(delta.x(), velocity)
        self._press = None
        self._target = None
        self._kind = None
        return consumed
