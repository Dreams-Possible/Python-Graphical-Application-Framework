"""历史事件展示组件：正文保持来源语言，界面标签使用应用资源。"""
from PySide6.QtCore import QDate, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFrame, QHBoxLayout, QVBoxLayout, QWidget
from src.shared.messages import message
from src.shared.widgets import plain_label, text_button, text_label
from src.features.calendar.history import HistoryState, safe_article


class HistoryEventsView(QWidget):
    refreshRequested = Signal()

    def __init__(self, texts, service=None):
        super().__init__()
        self.texts, self.service = texts, service
        self.day = QDate.currentDate()
        self._shown_events = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        row = QHBoxLayout()
        self.heading = plain_label(name="SectionTitle")
        self.retry = text_button(texts, "calendar.history.refresh")
        self.retry.clicked.connect(self.refreshRequested)
        row.addWidget(self.heading, 1)
        row.addWidget(self.retry)
        layout.addLayout(row)
        self.events = QVBoxLayout()
        self.events.setContentsMargins(0, 0, 0, 0)
        self.events.setSpacing(10)
        layout.addLayout(self.events)
        self.metadata = plain_label(name="Muted")
        layout.addWidget(self.metadata)
        self._anniversaries = []
        if service:
            service.changed.connect(self.render)
        texts.changed.connect(self.render)
        self.render()

    def set_day(self, day):
        self.day = QDate(day)
        self.render()

    def render(self):
        state = self.service.state if self.service else HistoryState()
        self.texts.bind_text(self.heading, "calendar.history.title", date=self.texts.short_date(self.day))
        self.retry.setEnabled(self.service is not None and not state.busy)
        language = message("settings.calendar.history_language." + state.language)
        self.texts.bind_text(self.metadata, "calendar.history.footer", status=state.status, language=language, count=len(state.events))
        self.texts.bind_text(self.metadata, "calendar.history.footer_hint", setter="setToolTip",
            scope=message("calendar.history.scope"), shown=len(state.events), total=state.total,
            source=message("calendar.history.source", language=language))
        self._update_anniversaries()
        if state.events == self._shown_events:
            return
        self._shown_events = state.events
        self._anniversaries = []
        while self.events.count():
            widget = self.events.takeAt(0).widget()
            if widget:
                widget.hide()
                widget.deleteLater()
        for event in state.events:
            card = QFrame()
            card.setObjectName("Card")
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 14, 16, 14)
            row.setSpacing(16)
            year = text_label(self.texts, "calendar.history.year_bce" if event.year < 0 else "calendar.history.year", "HistoryYear", year=abs(event.year))
            year.setMinimumWidth(80)
            year_column = QVBoxLayout()
            year_column.setSpacing(4)
            year_column.addWidget(year)
            anniversary = plain_label(name="Muted")
            self._anniversaries.append((anniversary, event.year))
            year_column.addWidget(anniversary)
            year_column.addStretch()
            row.addLayout(year_column)
            content = QVBoxLayout()
            content.setSpacing(8)
            content.addWidget(plain_label(event.text))
            if event.original_text:
                note = text_label(self.texts, "calendar.history.translated" if event.translation_status == "translated" else "calendar.history.translation_failed", "Muted")
                note.setToolTip(event.original_text)
                content.addWidget(note)
            if event.article:
                link = text_button(self.texts, "calendar.history.read_source")
                link.clicked.connect(lambda checked=False, url=event.article: self.open_article(url))
                content.addWidget(link, 0, Qt.AlignmentFlag.AlignLeft)
            row.addLayout(content, 1)
            self.events.addWidget(card)
        self._update_anniversaries()

    def _update_anniversaries(self):
        for label, year in self._anniversaries:
            years = self.day.year() - year - (1 if year < 0 < self.day.year() else 0)
            label.setVisible(years >= 0)
            if years > 0:
                self.texts.bind_text(label, "calendar.history.anniversary", years=years)
            elif years == 0:
                self.texts.bind_text(label, "calendar.history.same_year")

    @staticmethod
    def open_article(url):
        if safe_article(url):
            QDesktopServices.openUrl(QUrl(url))
