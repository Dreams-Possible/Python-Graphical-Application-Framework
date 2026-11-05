"""独立位置、手动定位和跨国家节假日隔离。"""
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from PySide6.QtCore import QObject, Signal, QDate
from src.features.location.service import LocationService, LocationFix, manual_location
from src.features.calendar.holidays import HolidayService, parse_international


class Tasks(QObject):
    completed = Signal(str, int, object, str, bool)
    activity_changed = Signal(int)
    def __init__(self):
        super().__init__()
        self.jobs = {}
        self.sequence = 0
    def submit(self, key, fn):
        self.sequence += 1
        self.jobs[key] = (self.sequence, fn)
        return self.sequence
    def cancel(self, key):
        pass
    def is_active(self, key):
        return key in self.jobs


class Configuration(QObject):
    changed = Signal(str)
    def __init__(self):
        super().__init__()
        self.location = dict(enabled=True, mode="manual", use_for_clock=False,
            manual_name="Tokyo", manual_country="JP", manual_latitude=35.6,
            manual_longitude=139.7, manual_timezone="Asia/Tokyo")
    def get(self, key):
        if key == "location":
            return self.location.copy()
        return {"holiday_url": "https://example.test/{year}", "international_url": "https://example.test/{country}/{year}", "timeout_seconds": 2}


class LocationCalendarTests(unittest.TestCase):
    def test_manual_location_runs_without_network_or_weather_consumer(self):
        tasks, config = Tasks(), Configuration()
        service = LocationService(config, tasks)
        updates = []
        service.updated.connect(updates.append)
        service.refresh()
        self.assertEqual(updates[-1].country_code, "JP")
        self.assertEqual(tasks.jobs, {})
        config.location["enabled"] = False
        service.refresh()
        self.assertIsNone(service.current)

    def test_manual_validation(self):
        values = Configuration().location
        self.assertEqual(manual_location(values).timezone, "Asia/Tokyo")
        for key, value in (("manual_country", "../"), ("manual_timezone", "Bad/Zone"), ("manual_latitude", 200)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                manual_location(dict(values, **{key: value}))

    def test_country_change_discards_old_response_and_data(self):
        tasks, config = Tasks(), Configuration()
        with TemporaryDirectory() as directory:
            service = HolidayService(tasks, Path(directory), config)
            service.ensure(2026)
            self.assertFalse(tasks.jobs)
            service.set_location(LocationFix("Shanghai", 31, 121, "Asia/Shanghai", "CN"))
            service.ensure(2026)
            old_key = next(iter(tasks.jobs))
            old_generation = tasks.jobs[old_key][0]
            service.set_location(LocationFix("Tokyo", 35, 139, "Asia/Tokyo", "JP"))
            service._completed(old_key, old_generation, None, "old error", False)
            self.assertEqual(service.country, "JP")
            self.assertEqual(service.data, {})
            self.assertEqual(service.messages, {})
            service.set_location(None)
            self.assertIn("未确定", service.status(2026))

    def test_international_filters_regional_holidays(self):
        common = dict(date="2026-01-01", countryCode="US", localName="New Year", types=["Public"])
        result = parse_international([dict(common, **{"global": True}), dict(common, **{"global": False, "localName": "Regional"})], 2026, "US")
        self.assertEqual(result["2026-01-01"].name, "New Year")
        with self.assertRaises(ValueError):
            parse_international([common], 2026, "JP")
