"""展开列的宽度、点击命中与收起行为。"""
import unittest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from src.features.weather.forecast_view import ForecastGraphic


class ForecastDetailsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.graphic = ForecastGraphic(hourly=True)
        row = ("10-25 16:00", "晴", "23 °C", "25 °C", "75%", "60%", "0 mm", "5 km/h")
        self.graphic.set_rows((row,) * 5, row[0])
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
