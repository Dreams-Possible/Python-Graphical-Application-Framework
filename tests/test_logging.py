"""验证日志持久化和界面缓冲上限；仅写临时目录。"""

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from src.shared.logging_service import LoggingService, _BufferHandler


class LoggingTests(unittest.TestCase):
    def test_file_and_buffer_receive_module_records(self):
        with TemporaryDirectory() as directory:
            service = LoggingService(Path(directory))
            try:
                logging.getLogger("workbench.test").warning("test module event")
                self.assertIn("test module event", service.path.read_text(encoding="utf-8"))
                self.assertTrue(any(entry.source == "workbench.test" for entry in service.buffer.drain()))
            finally:
                service.stop()

    def test_overflow_is_bounded_and_reported_once(self):
        handler = _BufferHandler(capacity=2)
        for index in range(4):
            handler.handle(logging.LogRecord("test", logging.INFO, "", 0, str(index), (), None))
        entries = handler.drain()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0].level, "WARNING")
        self.assertEqual([entry.message for entry in entries[1:]], ["2", "3"])
        self.assertEqual(handler.drain(), ())
