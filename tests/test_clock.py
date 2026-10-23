"""NTP 时间戳跨代处理与取消，不向外发送报文。"""

import struct
from threading import Event
import unittest
from unittest.mock import patch

from src.features.clock.service import NTP_EPOCH, _timestamp, query_time
from src.shared.tasks import TaskCancelled


class ClockTests(unittest.TestCase):
    def test_timestamp_before_and_after_2036(self):
        for unix in (1700000000.25, 2300000000.5):
            ntp = unix + NTP_EPOCH
            raw = struct.pack("!II", int(ntp) % 2 ** 32, int((ntp % 1) * 2 ** 32))
            self.assertAlmostEqual(_timestamp(raw, unix), unix)

    def test_cancel_before_network(self):
        cancelled = Event()
        cancelled.set()
        with patch("src.features.clock.service.socket.getaddrinfo") as resolve:
            with self.assertRaises(TaskCancelled):
                query_time({"server": "example.invalid"}, cancelled)
            resolve.assert_not_called()
