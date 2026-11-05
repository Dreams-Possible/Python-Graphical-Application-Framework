"""倒计时界面，与时钟页面共用主题。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSpinBox, QPushButton, QApplication
from src.shared.widgets import plain_label, text_button, text_label
from src.shared.localization import message
from src.features.clock.countdown import Countdown


class TimerView(QWidget):
    def __init__(self, texts, parent=None):
        super().__init__(parent)
        self.texts = texts
        self.model = Countdown(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)
        layout.addStretch()
        self.digits = plain_label("00:05:00", "ClockDigits")
        self.digits.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.digits)
        self.status = text_label(texts, "clock.timer.idle", "Muted")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status)
        fields = QHBoxLayout()
        fields.addStretch()
        self.inputs = []
        for name, maximum, value in (("clock.timer.hours", 99, 0), ("clock.timer.minutes", 59, 5), ("clock.timer.seconds", 59, 0)):
            editor = QSpinBox()
            editor.setRange(0, maximum)
            editor.setValue(value)
            texts.bind_text(editor, name, setter="setSuffix")
            texts.bind_text(editor, name, setter="setAccessibleName")
            editor.setFixedWidth(140)
            editor.valueChanged.connect(self.render)
            self.inputs.append(editor)
            fields.addWidget(editor)
        fields.addStretch()
        layout.addLayout(fields)
        row = QHBoxLayout()
        row.addStretch()
        self.action = QPushButton()
        self.action.setObjectName("Primary")
        self.action.clicked.connect(self.toggle)
        reset = text_button(texts, "clock.reset")
        reset.clicked.connect(self.model.reset)
        row.addWidget(self.action)
        row.addWidget(reset)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        self.model.changed.connect(self.render)
        self.model.finished.connect(self.notify)
        self.render()
        texts.changed.connect(self.render)

    def duration(self):
        return sum(editor.value() * factor for editor, factor in zip(self.inputs, (3600, 60, 1)))

    def toggle(self):
        if self.model.state == "running":
            self.model.pause()
        elif self.model.state == "paused":
            self.model.resume()
        else:
            self.model.start(self.duration())

    def render(self):
        state = self.model.state
        seconds = self.duration() if state == "idle" else self.model.seconds
        self.digits.setText(f"{seconds // 3600:02d}:{seconds // 60 % 60:02d}:{seconds % 60:02d}")
        for editor in self.inputs:
            editor.setEnabled(state in ("idle", "finished"))
        self.action.setText(self.texts.get({"running": "clock.pause", "paused": "clock.resume", "finished": "clock.timer.restart", "idle": "clock.timer.start"}[state]))
        self.action.setEnabled(state in ("running", "paused") or self.duration() > 0)
        self.texts.bind_text(self.status, "clock.timer." + state)

    def notify(self):
        QApplication.beep()
        window = self.window()
        QApplication.alert(window, 5000)
        if hasattr(window, "notifications"):
            window.notifications.report(message("clock.timer.notice"))
