"""Qt 核心事件循环测试，无窗口、无网络。"""

from threading import Event
import time
import unittest

from PySide6.QtCore import QCoreApplication

from src.shared.tasks import TaskRunner, check_cancelled


class TaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def drain(self, runner):
        deadline = time.monotonic() + 3
        while runner.active_count and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.002)
        self.app.processEvents()
        self.assertEqual(runner.active_count, 0)

    def test_success_and_exception(self):
        runner = TaskRunner()
        results = []
        runner.completed.connect(lambda *args: results.append(args))
        runner.submit("sample", lambda stop: 42)
        self.drain(runner)
        self.assertEqual(results[0][2], 42)

        def fail(stop):
            raise ValueError("expected")

        runner.submit("sample", fail)
        self.drain(runner)
        self.assertEqual(results[-1][3], "expected")

    def test_cancel_and_shutdown(self):
        runner = TaskRunner()
        results = []
        runner.completed.connect(lambda *args: results.append(args))

        def wait(stop: Event):
            stop.wait(1)
            check_cancelled(stop)

        runner.submit("sample", wait)
        with self.assertRaises(RuntimeError):
            runner.submit("sample", wait)
        runner.cancel("sample")
        self.drain(runner)
        self.assertTrue(results[0][4])
        runner.submit("sample", wait)
        self.assertFalse(runner.shutdown())
        self.drain(runner)
        self.assertEqual(len(results), 1)
        with self.assertRaises(RuntimeError):
            runner.submit("new", wait)
