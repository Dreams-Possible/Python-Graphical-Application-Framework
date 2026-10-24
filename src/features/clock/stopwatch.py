"""使用单调时钟累计运行时长，暂停时间不计入结果。"""
import time

from PySide6.QtCore import QObject, Signal


class Stopwatch(QObject):
    changed = Signal()

    def __init__(self, parent=None, now=time.monotonic):
        super().__init__(parent)
        self.now = now
        self.state = "idle"
        self._accumulated = 0.0
        self._started_at = 0.0

    @property
    def elapsed(self):
        if self.state == "running":
            return self._accumulated + self.now() - self._started_at
        return self._accumulated

    def start(self):
        if self.state == "running":
            return
        self._started_at = self.now()
        self.state = "running"
        self.changed.emit()

    def pause(self):
        if self.state != "running":
            return
        self._accumulated = self.elapsed
        self.state = "paused"
        self.changed.emit()

    def reset(self):
        self._accumulated = 0.0
        self.state = "idle"
        self.changed.emit()
