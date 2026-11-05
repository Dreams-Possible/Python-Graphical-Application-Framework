"""公共手势的归属、跟手切页、回弹以及原生输入保护。"""
import unittest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QListWidget, QVBoxLayout, QWidget
from src.shared.gestures import DragClickWidget, KineticScrollArea, SwipePages
from src.shared.island import IslandPages
from src.shared.ui_metrics import UI


class GestureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.windows = []

    def tearDown(self):
        for window in self.windows:
            window.close()
            window.deleteLater()
        self.app.processEvents()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def pages(self, first=None, island=False):
        children = [first or QWidget(), QWidget(), QWidget()]
        window = IslandPages(tuple((str(i), page) for i, page in enumerate(children))) if island else SwipePages(children)
        window.resize(700, 450)
        window.move(40, 40)
        window.show()
        self.windows.append(window)
        if self.app.platformName() == "windows":
            window.activateWindow()
            QTest.qWaitForWindowActive(window, 1000)
        self.app.processEvents()
        return window

    def drag(self, widget, delta, delay=35, release_wait=0, finish=True):
        point = widget.visibleRegion().boundingRect().center()
        origin = widget.mapToGlobal(point)
        QTest.mousePress(widget, Qt.MouseButton.LeftButton, pos=point)
        for part in (0.1, 0.3, 0.55, 0.8, 1.0):
            global_point = origin + QPoint(round(delta.x() * part), round(delta.y() * part))
            local = widget.mapFromGlobal(global_point)
            QApplication.sendEvent(widget, QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(global_point),
                Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
            QTest.qWait(delay)
        if finish:
            QTest.qWait(release_wait)
            QTest.mouseRelease(widget, Qt.MouseButton.LeftButton, pos=widget.mapFromGlobal(origin + delta))
            QTest.qWait(UI.page_slide_ms + 30)
        return origin

    def test_drag_follows_pointer_then_switches_and_updates_island(self):
        window = self.pages(island=True)
        page = window.pages[0]
        origin = self.drag(page, QPoint(-240, 0), finish=False)
        self.assertEqual(window.current, 0)
        self.assertLess(window.strip.x(), -100)
        QTest.mouseRelease(page, Qt.MouseButton.LeftButton, pos=page.mapFromGlobal(origin + QPoint(-240, 0)))
        QTest.qWait(UI.page_slide_ms + 30)
        self.assertEqual(window.current, 1)
        self.assertTrue(window.buttons[1].isChecked())
        self.assertEqual(window.strip.x(), -window.viewport.width())
        self.drag(window.pages[1], QPoint(240, 0))
        self.assertEqual(window.current, 0)

    def test_short_slow_drag_snaps_back_and_edges_do_not_wrap(self):
        window = self.pages()
        self.drag(window.pages[0], QPoint(-35, 0), delay=50, release_wait=250)
        self.assertEqual(window.current, 0)
        self.assertEqual(window.strip.x(), 0)
        self.drag(window.pages[0], QPoint(250, 0))
        self.assertEqual(window.current, 0)
        window.select(2)
        QTest.qWait(UI.page_slide_ms + 30)
        self.drag(window.pages[2], QPoint(-250, 0))
        self.assertEqual(window.current, 2)
        self.assertEqual(window.strip.x(), -2 * window.viewport.width())

    def test_fast_short_flick_can_switch(self):
        window = self.pages()
        self.drag(window.pages[0], QPoint(-100, 0), delay=5)
        self.assertEqual(window.current, 1)

    def test_horizontal_scroll_has_priority_even_at_its_boundary(self):
        area = KineticScrollArea(Qt.Orientation.Horizontal)
        canvas = DragClickWidget()
        canvas.setMinimumWidth(1800)
        area.setWidget(canvas)
        window = self.pages(area)
        self.drag(canvas, QPoint(-250, 0))
        self.assertGreater(area.horizontalScrollBar().value(), 0)
        self.assertEqual(window.current, 0)
        area.kinetic.stop()
        area.horizontalScrollBar().setValue(area.horizontalScrollBar().maximum())
        self.drag(canvas, QPoint(-250, 0))
        self.assertEqual(window.current, 0)

    def test_vertical_scroll_and_horizontal_paging_are_distinct(self):
        area = KineticScrollArea()
        content = QWidget()
        content.setMinimumHeight(1400)
        area.setWidget(content)
        window = self.pages(area)
        self.drag(content, QPoint(0, -250))
        self.assertGreater(area.verticalScrollBar().value(), 0)
        self.assertEqual(window.current, 0)
        area.kinetic.stop()
        self.drag(content, QPoint(-250, 0))
        self.assertEqual(window.current, 1)

    def test_inputs_and_drag_selection_lists_keep_their_events(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        edit = QLineEdit("This text is editable")
        listing = QListWidget()
        listing.addItems(["one", "two", "three"])
        layout.addWidget(edit)
        layout.addWidget(listing)
        window = self.pages(page)
        self.drag(edit, QPoint(-200, 0))
        self.assertEqual(window.current, 0)
        self.assertEqual(edit.text(), "This text is editable")
        self.drag(listing.viewport(), QPoint(-200, 0))
        self.assertEqual(window.current, 0)

    def test_resize_and_rapid_button_changes_settle_consistently(self):
        window = self.pages(island=True)
        page = window.pages[0]
        origin = self.drag(page, QPoint(-160, 0), finish=False)
        window.resize(800, 500)
        self.app.processEvents()
        QTest.mouseRelease(page, Qt.MouseButton.LeftButton, pos=page.mapFromGlobal(origin + QPoint(-160, 0)))
        QTest.qWait(UI.page_slide_ms + 30)
        self.assertEqual(window.current, 0)
        self.assertEqual(window.strip.x(), 0)
        window.buttons[2].click()
        window.buttons[1].click()
        QTest.qWait(UI.page_slide_ms + 30)
        self.assertEqual(window.current, 1)
        self.assertTrue(window.buttons[1].isChecked())
        self.assertEqual(window.strip.x(), -window.viewport.width())

    def test_swiping_preserves_timer_and_stopwatch_models(self):
        from src.shared.localization import Localization
        from src.features.clock.timer_view import TimerView
        from src.features.clock.stopwatch_view import StopwatchView
        texts = Localization(mode="en-US")
        timer, watch = TimerView(texts), StopwatchView(texts)
        window = IslandPages((("clock", QWidget()), ("watch", watch), ("timer", timer)))
        window.resize(800, 500)
        window.move(40, 40)
        window.show()
        self.windows.append(window)
        if self.app.platformName() == "windows":
            window.activateWindow()
            QTest.qWaitForWindowActive(window, 1000)
        self.app.processEvents()
        timer.model.start(600)
        watch.model.start()
        deadline, started = timer.model.deadline, watch.model._started_at
        self.drag(window.pages[0], QPoint(-240, 0))
        self.assertEqual(window.current, 1)
        self.drag(watch.digits, QPoint(-240, 0))
        self.assertEqual(window.current, 2)
        self.assertEqual(timer.model.deadline, deadline)
        self.assertEqual(watch.model._started_at, started)
        self.assertEqual(timer.model.state, "running")
        self.assertEqual(watch.model.state, "running")
