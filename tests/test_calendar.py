"""日历视角、选择状态和节假日解析。"""
import unittest
from PySide6.QtCore import QDate, QEvent, QPoint, QPointF, Qt, QCoreApplication
from PySide6.QtWidgets import QApplication, QBoxLayout
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QTest
from src.shared.ui_metrics import UI
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

    def drag_grid(self, grid, distance):
        viewport = grid.viewport()
        origin = viewport.mapToGlobal(viewport.rect().center())
        QTest.mousePress(viewport, Qt.MouseButton.LeftButton, pos=viewport.mapFromGlobal(origin))
        for part in (0.1, 0.3, 0.55, 0.8, 1):
            position = origin + QPoint(round(distance * part), 0)
            QApplication.sendEvent(viewport, QMouseEvent(QEvent.Type.MouseMove,
                QPointF(viewport.mapFromGlobal(position)), QPointF(position), Qt.MouseButton.NoButton,
                Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
            QTest.qWait(30)
        QTest.mouseRelease(viewport, Qt.MouseButton.LeftButton, pos=viewport.mapFromGlobal(origin + QPoint(distance, 0)))
        QTest.qWait(UI.page_slide_ms + 30)

    def test_month_year_swipes_preserve_date_and_click_doubleclick(self):
        view = CalendarView(ThemeManager(self.app), Localization(mode="zh-CN"))
        view.resize(900, 700)
        view.move(40, 40)
        view.date = view.shown = QDate(2026, 12, 13)
        view.show()
        if self.app.platformName() == "windows":
            view.activateWindow()
            QTest.qWaitForWindowActive(view, 1000)
        view.refresh()
        self.app.processEvents()
        try:
            self.drag_grid(view.month_grid, -240)
            self.assertEqual((view.shown.year(), view.shown.month()), (2027, 1))
            self.assertEqual(view.date, QDate(2026, 12, 13))
            self.assertEqual(view.month_pages.current, 1)
            self.drag_grid(view.month_grid, 240)
            self.assertEqual((view.shown.year(), view.shown.month()), (2026, 12))
            view.set_mode("year")
            self.drag_grid(view.year_grid, -240)
            self.assertEqual(view.shown.year(), 2027)
            self.assertEqual(view.date, QDate(2026, 12, 13))
            self.assertEqual(view.year_pages.current, 1)
            point = view.year_grid.visualItemRect(view.year_grid.item(0, 1)).center()
            QTest.mousePress(view.year_grid.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(view.date, QDate(2026, 12, 13))
            QTest.mouseRelease(view.year_grid.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.assertEqual(view.date, QDate(2027, 2, 1))
            QTest.mouseDClick(view.year_grid.viewport(), Qt.MouseButton.LeftButton, pos=point)
            self.app.processEvents()
            self.assertEqual(view.mode, "month")
            self.assertEqual((view.shown.year(), view.shown.month()), (2027, 2))
        finally:
            view.close()
            view.deleteLater()
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_holiday_refresh_is_right_of_today_and_toolbar_wraps(self):
        from PySide6.QtCore import QObject, Signal
        class Holidays(QObject):
            changed = Signal()
            def today(self): return QDate(2026, 11, 5)
            def ensure(self, year): pass
            def status(self, year): return ""
            def label(self, day): return ""
            def event(self, day): return None
            def text(self, day): return ""
            def retry(self, year): pass
        view = CalendarView(ThemeManager(self.app), Localization(mode="en-US"), Holidays())
        view.resize(1100, 650)
        view.show()
        self.app.processEvents()
        self.assertEqual(view.today_button.parentWidget(), view.retry.parentWidget())
        self.assertGreater(view.retry.x(), view.today_button.x())
        view.resize(620, 650)
        self.app.processEvents()
        self.assertEqual(view._toolbar_layout.direction(), QBoxLayout.Direction.TopToBottom)
        self.assertGreater(view.retry.x(), view.today_button.x())
        view.close()
