"""只操作临时目录的会话日志，不清理真实用户文件。"""

import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest
from unittest.mock import patch

from src.features.logs.repository import LogRepository
from src.shared.logging_service import LoggingService


class LogRepositoryTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.service = LoggingService(self.directory)
        self.addCleanup(self.service.stop)
        self.repository = LogRepository(self.service)
        self.stop = Event()

    def test_history_formats_and_traceback(self):
        path = self.directory / "session-20260101-000000-000000.log"
        path.write_text("[INFO] | 2026-01-01 10:00:00 | workbench.old | old message\n"
                        "[ERROR] | 2026-01-01 10:00:01 | MainThread | workbench.new | failed\n"
                        "Traceback details\n", encoding="utf-8")
        self.assertEqual(self.repository.files(self.stop), (path.name,))
        result = self.repository.read(path.name, 10, self.stop)
        self.assertEqual([entry.level for entry in result.entries], ["INFO", "ERROR", "ERROR"])
        self.assertEqual(result.entries[-1].message, "Traceback details")
        limited = self.repository.read(path.name, 1, self.stop)
        self.assertTrue(limited.limited)
        self.assertEqual(len(limited.entries), 1)

    def test_reject_paths_outside_directory(self):
        for name in ("../session-secret.log", "/tmp/session-secret.log", "configuration.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.repository.read(name, 10, self.stop)

    def test_clear_keeps_current_writer_and_unrelated_files(self):
        old = self.directory / "session-old.log"
        old.write_text("old history", encoding="utf-8")
        unrelated = self.directory / "notes.txt"
        unrelated.write_text("keep", encoding="utf-8")
        logging.getLogger("workbench.test").info("before cleanup")
        removed, failures = self.repository.clear_all(self.stop)
        self.assertEqual((removed, failures), (1, ()))
        self.assertFalse(old.exists())
        self.assertEqual(unrelated.read_text(), "keep")
        logging.getLogger("workbench.test").info("after cleanup")
        content = self.service.path.read_text(encoding="utf-8")
        self.assertNotIn("before cleanup", content)
        self.assertIn("after cleanup", content)

    def test_failed_delete_is_reported(self):
        old = self.directory / "session-old.log"
        old.write_text("keep", encoding="utf-8")
        with patch.object(Path, "unlink", side_effect=PermissionError("denied")):
            removed, failures = self.repository.clear_all(self.stop)
        self.assertEqual(removed, 0)
        self.assertIn(old.name, failures)
        self.assertTrue(old.exists())
