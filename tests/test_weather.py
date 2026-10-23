"""天气解析使用固定响应，不访问网络。"""

import unittest

from src.features.weather.providers import parse_report


class WeatherTests(unittest.TestCase):
    def test_local_day_hourly_window_and_history(self):
        midnight = 1729987200
        offset = 8 * 3600
        local_midnight = midnight - offset
        current = local_midnight + 12 * 3600 + 15 * 60
        document = {
            "utc_offset_seconds": offset, "timezone": "Asia/Shanghai",
            "current": {"time": current, "temperature_2m": 20, "weather_code": 0},
            "hourly": {"time": [local_midnight + hour * 3600 for hour in range(48)]},
            "daily": {"time": [local_midnight + day * 86400 for day in range(-2, 16)]},
        }
        report = parse_report(document, {"location_name": "测试地点"})
        self.assertEqual(len(report.hourly), 24)
        self.assertTrue(report.hourly[0][0].endswith("12:00"))
        self.assertEqual(len(report.daily), 16)
        self.assertEqual(len(report.history), 2)
        self.assertEqual(report.hourly[0][2], "—")

    def test_reject_incomplete_response(self):
        with self.assertRaises(ValueError):
            parse_report({"current": {}}, {"location_name": "测试"})
