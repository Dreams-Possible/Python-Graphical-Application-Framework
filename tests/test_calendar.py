"""日历视角、选择状态和节假日解析。"""
import unittest
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import QApplication
from src.features.calendar.view import CalendarView
from src.features.calendar.holidays import parse_days
from src.shared.theme import ThemeManager
from src.shared.localization import Localization


class CalendarTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_view_switch_preserves_selected_date(self):
        themes = ThemeManager(self.app)
        view = CalendarView(themes, Localization(mode="zh-CN"))
        view.shown = view.date = QDate(2026, 11, 5)
        view.refresh()
        item = view.month_grid.item(1, 0)
        expected = item.data(Qt.ItemDataRole.UserRole)
        view.month_grid.setCurrentItem(item)
        self.assertEqual(view.date, expected)
        self.assertEqual(len(view.month_grid.selectedItems()), 1)
        view.set_mode("day")
        self.assertEqual(view.date, expected)
        view.step(1)
        self.assertEqual(view.date, expected.addDays(1))
        view.set_mode("year")
        self.assertEqual(view.year_grid.rowCount() * view.year_grid.columnCount(), 12)
        view.shown = QDate(2026, 12, 1)
        view.mode = "month"
        view.step(1)
        self.assertEqual(view.shown, QDate(2027, 1, 1))
        view.go_today()
        self.assertEqual(view.date, QDate.currentDate())
        view.close()

    def test_holiday_off_day_and_adjusted_workday(self):
        data = {"year": 2026, "days": [
            {"date": "2026-01-01", "name": "元旦", "isOffDay": True},
            {"date": "2026-01-04", "name": "元旦", "isOffDay": False}]}
        result = parse_days(data, 2026)
        self.assertTrue(result["2026-01-01"].off)
        self.assertFalse(result["2026-01-04"].off)
        with self.assertRaises(ValueError):
            parse_days(data, 2027)
