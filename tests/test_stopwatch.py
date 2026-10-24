import unittest

from src.features.clock.stopwatch import Stopwatch


class StopwatchTests(unittest.TestCase):
    def test_delayed_refresh_pause_and_resume(self):
        now = [100.0]
        model = Stopwatch(now=lambda: now[0])
        model.start()
        now[0] += 65.125
        self.assertAlmostEqual(model.elapsed, 65.125)
        model.start()  # 重复开始不得丢失已计时间。
        model.pause()
        now[0] += 200
        self.assertAlmostEqual(model.elapsed, 65.125)
        model.start()
        now[0] += 2.25
        model.pause()
        self.assertAlmostEqual(model.elapsed, 67.375)

    def test_reset_while_running_or_paused(self):
        now = [0.0]
        model = Stopwatch(now=lambda: now[0])
        for pause_first in (False, True):
            model.start()
            now[0] += 5
            if pause_first:
                model.pause()
            model.reset()
            now[0] += 10
            self.assertEqual(model.elapsed, 0)
            self.assertEqual(model.state, "idle")
