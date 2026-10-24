"""秒表页面：计时独立于刷新，隐藏页面不刷新数字。"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QPushButton

from src.features.clock.stopwatch import Stopwatch
from src.shared.widgets import plain_label


class StopwatchView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.model = Stopwatch(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)
        layout.addStretch()
        self.digits = plain_label("00:00:00.00", "ClockDigits")
        self.digits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.digits)
        self.status = plain_label(name="Muted")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        row = QHBoxLayout()
        row.addStretch()
        self.action = QPushButton("开始")
        self.action.setObjectName("Primary")
        self.action.clicked.connect(self.toggle)
        self.reset_button = QPushButton("重置")
        self.reset_button.clicked.connect(self.model.reset)
        row.addWidget(self.action)
        row.addWidget(self.reset_button)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.render)
        self.model.changed.connect(self.render)
        self.render()

    def toggle(self):
        if self.model.state == "running":
            self.model.pause()
        else:
            self.model.start()

    def render(self):
        hundredths = int(self.model.elapsed * 100)
        seconds, fraction = divmod(hundredths, 100)
        self.digits.setText(f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}.{fraction:02d}")
        state = self.model.state
        self.action.setText({"idle": "开始", "running": "暂停", "paused": "继续"}[state])
        self.status.setText({"idle": "点击开始，记录经过的时间", "running": "计时中 · 切换页面后继续运行", "paused": "已暂停"}[state])
        self.reset_button.setEnabled(state != "idle")
        if state == "running" and self.isVisible():
            self.timer.start()
        else:
            self.timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.render()

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)
