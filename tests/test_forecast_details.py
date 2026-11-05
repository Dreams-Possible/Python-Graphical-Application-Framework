"""展开列的宽度、点击命中与收起行为。"""
import unittest
from datetime import datetime
from src.shared.localization import Localization
from src.features.weather.models import ForecastPoint
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QScroller
from src.features.weather.forecast_view import ForecastGraphic


class ForecastDetailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.graphic = ForecastGraphic(Localization(mode="zh-CN"), hourly=True)
        row = ForecastPoint(datetime(2026, 10, 25, 16), 0, temperature=23, apparent=25, humidity=75, precipitation_probability=60, precipitation=0, wind=5)
        self.graphic.set_rows((row,) * 5, "10-25 16:00")
        self.graphic.show()
        self.app.processEvents()

    def tearDown(self):
        self.graphic.close()

    def test_click_expands_in_place_without_changing_current(self):
        QTest.mouseClick(self.graphic, Qt.MouseButton.LeftButton, pos=QPoint(150, 50))
        self.assertEqual(self.graphic.selected_index, 1)
        self.assertEqual(self.graphic.current_index, 0)
        self.assertEqual(self.graphic._column_rect(1).width(), 280)
        self.assertEqual(self.graphic.minimumWidth(), 5 * 104 + 176)
        self.assertEqual(self.graphic._index_at(QPointF(350, 50)), 1)
        self.assertFalse(hasattr(self.graphic, "sticker"))

    def test_select_other_column_restores_previous_width(self):
        self.graphic._toggle_details(1)
        self.graphic._toggle_details(2)
        self.assertEqual(self.graphic._column_rect(1).width(), 104)
        self.assertEqual(self.graphic._column_rect(2).width(), 280)
        self.assertEqual(self.graphic.selected_index, 2)

    def test_same_column_escape_and_new_data_collapse(self):
        self.graphic._toggle_details(1)
        self.graphic._toggle_details(1)
        self.assertEqual(self.graphic.selected_index, -1)
        self.assertEqual(self.graphic.minimumWidth(), 520)
        self.graphic._toggle_details(1)
        QTest.keyClick(self.graphic, Qt.Key.Key_Escape)
        self.assertEqual(self.graphic.selected_index, -1)
        self.graphic._toggle_details(1)
        self.graphic.set_rows(())
        self.assertEqual(self.graphic.selected_index, -1)

    def test_press_waits_for_release_and_drag_back_does_not_click(self):
        start = QPoint(150, 50)
        QTest.mousePress(self.graphic, Qt.MouseButton.LeftButton, pos=start)
        self.assertEqual(self.graphic.selected_index, -1)
        QTest.mouseRelease(self.graphic, Qt.MouseButton.LeftButton, pos=start)
        self.assertEqual(self.graphic.selected_index, 1)
        QTest.mousePress(self.graphic, Qt.MouseButton.LeftButton, pos=start)
        moved = start + QPoint(QApplication.startDragDistance() + 20, 0)
        event = QMouseEvent(QEvent.Type.MouseMove, QPointF(moved), QPointF(self.graphic.mapToGlobal(moved)),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(self.graphic, event)
        QTest.mouseRelease(self.graphic, Qt.MouseButton.LeftButton, pos=start)
        self.assertEqual(self.graphic.selected_index, 1)

    def test_kinetic_drag_scrolls_without_opening_details(self):
        from src.features.weather.view import WeatherDetails
        details = WeatherDetails(Localization(mode="en-US"))
        details.resize(800, 650)
        point = ForecastPoint(datetime(2026, 11, 5, 12), 0, temperature=20)
        details.hours.set_rows((point,) * 24)
        details.show()
        self.app.processEvents()
        area = details.forecast_scrollers[0]
        graphic = details.hours
        kinetic = QScroller.scroller(area.viewport())
        states = []
        kinetic.stateChanged.connect(states.append)
        try:
            self.assertGreater(area.horizontalScrollBar().maximum(), 0)
            start = QPoint(400, 120)
            origin = graphic.mapToGlobal(start)
            QTest.mousePress(graphic, Qt.MouseButton.LeftButton, pos=start)
            self.assertEqual(graphic.selected_index, -1)
            for distance in (20, 60, 110, 170, 230):
                global_point = origin - QPoint(distance, 0)
                local = graphic.mapFromGlobal(global_point)
                event = QMouseEvent(QEvent.Type.MouseMove, QPointF(local), QPointF(global_point),
                                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(graphic, event)
                QTest.qWait(35)
            QTest.mouseRelease(graphic, Qt.MouseButton.LeftButton, pos=graphic.mapFromGlobal(origin - QPoint(230, 0)))
            QTest.qWait(80)
            self.assertGreater(area.horizontalScrollBar().value(), 0)
            self.assertEqual(details.scroll.verticalScrollBar().value(), 0)
            self.assertIn(QScroller.State.Scrolling, states)
            self.assertEqual(graphic.selected_index, -1)
            kinetic.stop()
            area.horizontalScrollBar().setValue(0)
            self.app.processEvents()
            QTest.mouseClick(graphic, Qt.MouseButton.LeftButton, pos=QPoint(150, 100))
            QTest.qWait(50)
            self.assertEqual(graphic.selected_index, 1)
        finally:
            kinetic.stop()
            details.close()

    def test_hour_titles_use_time_only_including_current_hour(self):
        self.assertEqual(self.graphic.column_title(0), "16:00")
        self.assertEqual(self.graphic.column_title(1), "16:00")
        self.graphic.texts.set_language("en-US")
        self.assertEqual(self.graphic.column_title(0), "16:00")

    def test_vertical_drag_over_chart_scrolls_outer_details(self):
        from src.features.weather.view import WeatherDetails
        details = WeatherDetails(Localization(mode="zh-CN"))
        details.resize(800, 650)
        details.hours.set_rows((ForecastPoint(datetime(2026, 11, 5, 12), 0, temperature=20),) * 24)
        details.show()
        self.app.processEvents()
        graphic = details.hours
        area = details.forecast_scrollers[0]
        start = QPoint(400, 150)
        origin = graphic.mapToGlobal(start)
        try:
            self.assertGreater(details.scroll.verticalScrollBar().maximum(), 0)
            QTest.mousePress(graphic, Qt.MouseButton.LeftButton, pos=start)
            for distance in (20, 60, 110, 170, 230):
                global_point = origin - QPoint(0, distance)
                event = QMouseEvent(QEvent.Type.MouseMove, QPointF(graphic.mapFromGlobal(global_point)), QPointF(global_point),
                                   Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
                QApplication.sendEvent(graphic, event)
                QTest.qWait(35)
            QTest.mouseRelease(graphic, Qt.MouseButton.LeftButton, pos=graphic.mapFromGlobal(origin - QPoint(0, 230)))
            QTest.qWait(80)
            self.assertGreater(details.scroll.verticalScrollBar().value(), 0)
            self.assertEqual(area.horizontalScrollBar().value(), 0)
            self.assertEqual(graphic.selected_index, -1)
        finally:
            for scroller in (details.scroll, *details.forecast_scrollers):
                QScroller.scroller(scroller.viewport()).stop()
            details.close()
