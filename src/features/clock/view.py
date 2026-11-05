"""时钟页面只渲染快照并转发用户操作。"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from src.features.clock.view_model import ClockState, ClockViewModel
from src.shared.island import IslandPages
from src.features.clock.timer_view import TimerView
from src.features.clock.stopwatch_view import StopwatchView
from src.shared.widgets import page_layout, plain_label, text_button


class ClockView(QWidget):
    def __init__(self, model: ClockViewModel, texts) -> None:
        super().__init__()
        self.model = model
        self.texts = texts
        layout = page_layout(self, "clock.page.title", "clock.page.subtitle", texts=texts)
        clock_page = QWidget()
        clock_layout = QVBoxLayout(clock_page)
        clock_layout.setContentsMargins(0, 0, 0, 0)
        clock_layout.setSpacing(16)
        self.timer_view = TimerView(texts)
        self.stopwatch_view = StopwatchView(texts)
        self.sections = IslandPages((("clock.tab.clock", clock_page), ("clock.tab.stopwatch", self.stopwatch_view), ("clock.tab.timer", self.timer_view)), texts=texts)
        layout.addWidget(self.sections, 1)
        card = QFrame()
        card.setObjectName("ClockCard")
        inner = QVBoxLayout(card)
        inner.setContentsMargins(24, 20, 24, 20)
        inner.setSpacing(12)
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
        self.sync = text_button(texts, "clock.sync")
        self.sync.setObjectName("Primary")
        self.cancel = text_button(texts, "clock.cancel")
        self.sync.clicked.connect(model.synchronize)
        self.cancel.clicked.connect(model.cancel)
        actions.addWidget(self.sync)
        actions.addWidget(self.cancel)
        actions.addStretch()
        clock_layout.addStretch()
        card.setMaximumWidth(820)
        clock_layout.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        clock_layout.addLayout(actions)
        clock_layout.addStretch()
        model.changed.connect(self.render)
        self.render(model.state)
        texts.changed.connect(self.retranslate)

    def retranslate(self):
        self.render(self.model.state)

    @Slot(object)
    def render(self, state: ClockState) -> None:
        self.time.setText(self.texts.time(state.current, seconds=state.show_seconds))
        self.date.setText(self.texts.date(state.current.date(), long=True))
        zone = self.texts.get("clock.zone", zone=state.timezone_id, offset=state.current.strftime("%z"))
        self.zone.setText(self.texts.get("clock.zone_location", zone=zone) if state.location_timezone else zone)
        self.status.setText(self.texts.get("clock.state." + state.status_code))
        self.status.setProperty("failed", state.failed)
        self.status.style().unpolish(self.status)
        self.status.style().polish(self.status)
        detail = self.texts.render(state.error) if state.error else self.texts.get("clock.detail", server=state.server,
            time=self.texts.time(state.last_sync) if state.last_sync else self.texts.get("clock.never_synced"))
        if state.offset_seconds is not None:
            detail = self.texts.get("clock.detail_offset", detail=detail, offset=self.texts.number(state.offset_seconds * 1000, 0))
        self.detail.setText(detail)
        self.sync.setEnabled(not state.busy)
        self.cancel.setEnabled(state.busy)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.model.set_active(True)

    def hideEvent(self, event) -> None:
        self.model.set_active(False)
        super().hideEvent(event)
