"""时钟页面只渲染快照并转发用户操作。"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from src.features.clock.view_model import ClockState, ClockViewModel
from src.shared.widgets import page_layout, plain_label


class ClockView(QWidget):
    def __init__(self, model: ClockViewModel) -> None:
        super().__init__()
        self.model = model
        layout = page_layout(self, "时钟", "从网络校准时间，让每一天从准确的节奏开始。")
        card = QFrame()
        card.setObjectName("ClockCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(36, 36, 36, 36)
        inner.setSpacing(20)
        self.date = plain_label(name="SectionTitle")
        self.time = plain_label(name="ClockDigits")
        self.zone = plain_label(name="Muted")
        self.status = plain_label(name="Status")
        self.detail = plain_label(name="Muted")
        for label in (self.date, self.time, self.zone, self.status, self.detail):
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            inner.addWidget(label)
        actions = QHBoxLayout()
        actions.addStretch()
        self.sync = QPushButton("立即同步")
        self.sync.setObjectName("Primary")
        self.cancel = QPushButton("取消同步")
        self.sync.clicked.connect(model.synchronize)
        self.cancel.clicked.connect(model.cancel)
        actions.addWidget(self.sync)
        actions.addWidget(self.cancel)
        actions.addStretch()
        layout.addStretch()
        layout.addWidget(card)
        layout.addLayout(actions)
        layout.addStretch()
        model.changed.connect(self.render)
        self.render(model.state)

    @Slot(object)
    def render(self, state: ClockState) -> None:
        self.time.setText(state.time_text)
        self.date.setText(state.date_text)
        self.zone.setText(state.timezone_text)
        self.status.setText(state.status)
        self.status.setProperty("failed", state.failed)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        self.detail.setText(state.detail)
        self.sync.setEnabled(not state.busy)
        self.cancel.setEnabled(state.busy)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.model.set_active(True)

    def hideEvent(self, event) -> None:
        self.model.set_active(False)
        super().hideEvent(event)
