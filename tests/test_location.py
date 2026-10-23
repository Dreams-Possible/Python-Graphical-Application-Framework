"""使用伪响应验证网络定位，不发送公网请求。"""

import unittest

from src.features.location.service import parse_location


class LocationTests(unittest.TestCase):
    def document(self):
        return {"success": True, "city": "Test", "country": "Test", "latitude": 30.0,
                "longitude": 120.0, "timezone": {"id": "UTC"}}

    def test_valid_location_and_deduplicated_label(self):
        fix = parse_location(self.document())
        self.assertEqual(fix.name, "Test")
        self.assertEqual(fix.latitude, 30)
        self.assertEqual(fix.timezone, "UTC")

    def test_reject_invalid_responses(self):
        for changes in ({"success": False}, {"latitude": float("nan")}, {"longitude": 181},
                        {"latitude": True}, {"timezone": {}}, {"timezone": {"id": "Invalid/Zone"}}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                parse_location(dict(self.document(), **changes))
