"""以临时配置和固定演示数据截取真实 Qt 界面，不联网、不读取用户配置。"""
from datetime import datetime, timedelta, timezone
from math import sin
from pathlib import Path
from tempfile import TemporaryDirectory
from time import time
from unittest.mock import PropertyMock, patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QCoreApplication, QDate, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from src.app.bootstrap import create_main_window
from src.features.calendar.history import HistoryEvent, HistoryQuery, HistorySnapshot
from src.features.clock.view_model import ClockState
from src.features.weather.models import ForecastPoint, WeatherReport
from src.shared.localization import Localization
from src.shared.logging_service import LoggingService
from src.shared.messages import message
from src.shared.paths import UserPaths
from src.shared.theme import ThemeManager
from src.shared.ui_metrics import UI

OUTPUT = ROOT / "docs" / "images" / "screenshots"
SAMPLE_TIME = datetime(2026, 11, 6, 9, 41, tzinfo=timezone(timedelta(hours=8)))


def weather_sample():
    hours = tuple(ForecastPoint(SAMPLE_TIME.replace(minute=0) + timedelta(hours=index),
        3 if index < 4 else 0, round(19 + 4 * sin(index / 4), 1), humidity=65,
        precipitation_probability=10 if index < 4 else 0, wind=7 + index % 4)
        for index in range(24))
    days = tuple(ForecastPoint(SAMPLE_TIME + timedelta(days=index),
        (0, 2, 3, 61, 2, 0)[index % 6], minimum=round(15 + sin(index), 1), maximum=round(23 + 2 * sin(index), 1))
        for index in range(16))
    return WeatherReport("上海 / 中国", 21.4, 2, 65, 8.2, SAMPLE_TIME, "Asia/Shanghai",
                         hours, days, (), "Open-Meteo")


def main():
    app = QApplication.instance() or QApplication([])
    OUTPUT.mkdir(parents=True, exist_ok=True)
    sample = ClockState(SAMPLE_TIME, True, "Asia/Shanghai", True, "network",
                        "ntp.aliyun.com", SAMPLE_TIME - timedelta(minutes=2), 0.024, "", False, False)
    with TemporaryDirectory(prefix="daylight-screenshots-") as directory:
        base = Path(directory)
        paths = UserPaths(*(base / name for name in ("config", "data", "cache", "logs")))
        paths.ensure()
        logs = LoggingService(paths.logs)
        logs.logger.removeHandler(logs.terminal)
        texts = Localization(mode="zh-CN", system_languages=["zh-CN"])
        themes = ThemeManager(app)
        window = None
        try:
            with patch("src.app.bootstrap.QTimer.singleShot"), patch("src.shared.tasks.TaskRunner.submit", return_value=1), \
                 patch("src.features.clock.view_model.ClockViewModel.state", new_callable=PropertyMock, return_value=sample):
                window = create_main_window(paths, logs, themes, texts)
                window.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen)
                window.resize(1400, 940)
                window.show()
                configuration = themes.configuration
                configuration.update("appearance", theme="light", language="zh-CN")
                clock, weather, calendar = (window._pages.widget(index) for index in range(3))

                def capture(name):
                    QTest.qWait(UI.page_slide_ms + 80)
                    app.processEvents()
                    path = OUTPUT / name
                    if not window.grab().save(str(path), "PNG", 0):
                        raise OSError(f"Could not save screenshot: {path}")
                    print(path.relative_to(ROOT))

                window._pages.setCurrentIndex(0)
                clock.render(sample)
                capture("main-clock.png")

                configuration.update("appearance", theme="dark")
                window._pages.setCurrentIndex(1)
                weather.model._set(report=weather_sample(), busy=False, error="", status=message("weather.state.updated"))
                capture("weather-dark.png")

                configuration.update("appearance", theme="light")
                window._pages.setCurrentIndex(0)
                clock.timer_view.inputs[1].setValue(25)
                clock.timer_view.model.now = lambda: 1000.0
                clock.timer_view.model.start(1500)
                clock.sections.select(2)
                capture("timer.png")

                with patch.object(calendar.history, "load"):
                    window._pages.setCurrentIndex(2)
                    calendar.date = calendar.shown = QDate(2026, 7, 20)
                    calendar.set_mode("day")
                    query = HistoryQuery(7, 20, "en", "https://en.wikipedia.org/{month}/{day}", 10, target_language="zh-CN")
                    snapshot = HistorySnapshot(query, time(), (
                        HistoryEvent(1976, "维京一号着陆器成功降落在火星表面。", "https://en.wikipedia.org/wiki/Viking_1",
                                     "Viking 1 successfully lands on Mars.", "translated"),
                        HistoryEvent(1969, "Apollo 11 lands on the Moon.", "https://en.wikipedia.org/wiki/Apollo_11",
                                     "Apollo 11 lands on the Moon.", "pending"),
                    ))
                    calendar.history._publish(query, snapshot, message("calendar.history.translating", done=1, total=2), True)
                    capture("calendar-history.png")

                    calendar.set_mode("month")
                    configuration.update("appearance", language="ru-RU")
                    capture("calendar-russian.png")
        finally:
            if window is not None:
                window.close()
                window.deleteLater()
                QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            texts.release_qt_translation()
            logs.stop()


if __name__ == "__main__":
    main()
