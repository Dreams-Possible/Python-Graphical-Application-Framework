"""倒计时使用单调时钟计算截止时间，避免界面刷新延迟累计误差。"""
import math
import time
from PySide6.QtCore import QObject, QTimer, Signal


class Countdown(QObject):
    changed = Signal()
    finished = Signal()

    def __init__(self, parent=None, now=time.monotonic):
        super().__init__(parent)
        self.now = now
        self.remaining = 0.0
        self.deadline = 0.0
        self.state = "idle"
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self.tick)

    @property
    def seconds(self):
        return math.ceil(max(0, self.deadline - self.now()) if self.state == "running" else self.remaining)

    def start(self, seconds):
        if seconds <= 0:
            return
        self.remaining = float(seconds)
        self.resume()

    def resume(self):
        if self.remaining <= 0:
            return
        self.deadline = self.now() + self.remaining
        self.state = "running"
        self.timer.start()
        self.changed.emit()

    def pause(self):
        if self.state != "running":
            return
        self.tick()
        if self.state != "running":
            return
        self.remaining = max(0, self.deadline - self.now())
        self.state = "paused"
        self.timer.stop()
        self.changed.emit()

    def reset(self):
        self.timer.stop()
        self.remaining = 0
        self.state = "idle"
        self.changed.emit()

    def tick(self):
        if self.state != "running":
            return
        if self.now() >= self.deadline:
            self.remaining = 0
            self.state = "finished"
            self.timer.stop()
            self.changed.emit()
            self.finished.emit()
        else:
            self.changed.emit()
