import unittest
from unittest.mock import patch
from src.features.clock.countdown import Countdown


class CountdownTests(unittest.TestCase):
    def test_pause_resume_and_expire_once(self):
        now = [100.0]
        with patch("src.features.clock.countdown.QTimer"):
            model = Countdown(now=lambda: now[0])
            completed = []
            model.finished.connect(lambda: completed.append(True))
            model.start(10)
            now[0] += 3.25
            model.pause()
            self.assertEqual(model.seconds, 7)
            now[0] += 100
            self.assertEqual(model.seconds, 7)
            model.resume()
            now[0] += 7
            model.tick()
            model.tick()
            self.assertEqual(completed, [True])
            self.assertEqual(model.seconds, 0)
            model.reset()
            self.assertEqual(model.state, "idle")
            model.start(0)
            self.assertEqual(model.state, "idle")
