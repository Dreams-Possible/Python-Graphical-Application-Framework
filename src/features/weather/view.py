"""天气详情与地点选择；纵向展示当前天气、小时趋势及每日预报。"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QListWidget, QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.shared.island import IslandPages
from src.shared.gestures import KineticScrollArea
from src.features.weather.models import WeatherState
from src.features.weather.view_model import WeatherViewModel
from src.shared.widgets import NavigationDelegate, page_layout, plain_label, text_label, text_button
from src.features.weather.forecast_view import ForecastGraphic, WeatherSymbol
from src.features.weather.presentation import condition, measurement


class WeatherDetails(QWidget):
    """当前天气与搜索页共同使用的天气详情。"""
    def __init__(self, texts):
        super().__init__()
        self.texts = texts
        self._report = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = KineticScrollArea()
        self.scroll.setWidgetResizable(True)
        outer.addWidget(self.scroll)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 0, 12, 96)
        layout.setSpacing(16)
        self.scroll.setWidget(content)
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        self.temperature = plain_label("—", "Temperature")
        self.symbol = WeatherSymbol(texts)
        self.summary = text_label(texts, "weather.empty", "SectionTitle")
        self.summary.setWordWrap(True)
        card_layout.addWidget(self.temperature)
        card_layout.addWidget(self.symbol)
        card_layout.addSpacing(24)
        card_layout.addWidget(self.summary, 1)
        layout.addWidget(card)
        self.hours = ForecastGraphic(texts, hourly=True)
        self.days = ForecastGraphic(texts)
        self.history = ForecastGraphic(texts)
        self.section_titles = []
        for title, graphic in (("weather.section.hours", self.hours), ("weather.section.days", self.days), ("weather.section.history", self.history)):
            section = QFrame()
            section.setObjectName("Card")
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(20, 16, 20, 16)
            heading = text_label(texts, title, "SectionTitle")
            self.section_titles.append(heading)
            section_layout.addWidget(heading)
            if graphic.hourly:
                section_layout.addWidget(text_label(texts, "weather.hint.hours", "Muted"))
            else:
                section_layout.addWidget(text_label(texts, "weather.hint.days", "Muted"))
            scroller = KineticScrollArea(Qt.Orientation.Horizontal)
            scroller.setWidgetResizable(True)
            scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroller.setWidget(graphic)
            scroller.viewport().setAutoFillBackground(False)
            section_layout.addWidget(scroller)
            layout.addWidget(section)
        self.forecast_scrollers = content.findChildren(QScrollArea)
        self._resize_forecasts()
        source = QLabel()
        texts.bind_text(source, "weather.credits")
        source.setOpenExternalLinks(True)
        source.setObjectName("Muted")
        layout.addWidget(source)
        layout.addStretch()
        texts.changed.connect(self.retranslate)

    def retranslate(self):
        if hasattr(self, "_state"):
            self.render(self._state, force=True)

    def render(self, state, force=False):
        self._state = state
        data_changed = state.report != self._report
        if not data_changed and not force:
            return
        self._report = state.report
        if state.report is None:
            self.temperature.setText("—")
            self.symbol.set_condition(None)
            self.texts.bind_text(self.section_titles[1], "weather.section.days")
            self.texts.bind_text(self.section_titles[2], "weather.section.history")
            self.texts.bind_text(self.summary, "weather.empty")
            for table in (self.hours, self.days, self.history):
                table.set_rows(())
            self._resize_forecasts()
            return
        report = state.report
        self.temperature.setText(measurement(self.texts, report.temperature, "temperature"))
        self.symbol.set_condition(report.weather_code)
        self.texts.bind_text(self.summary, "weather.summary", location=report.location,
            condition=condition(self.texts, report.weather_code), humidity=measurement(self.texts, report.humidity, "percent"),
            wind=measurement(self.texts, report.wind, "wind"), observed=self.texts.date(report.observed_at.date()) + " " + self.texts.time(report.observed_at, seconds=False), zone=report.timezone)
        if data_changed:
            self.hours.set_rows(report.hourly, report.observed_at.strftime("%m-%d %H:00"))
            self.days.set_rows(report.daily, report.observed_at.date().isoformat())
            self.history.set_rows(report.history)
        self.texts.bind_text(self.section_titles[1], "weather.section.days_count", count=len(report.daily))
        self.texts.bind_text(self.section_titles[2], "weather.section.history_count", count=len(report.history))
        self._resize_forecasts()

    def _resize_forecasts(self):
        for scroller in self.forecast_scrollers:
            scroller.setFixedHeight(scroller.widget().height() + 18)



class WeatherView(QWidget):
    def __init__(self, model: WeatherViewModel, texts) -> None:
        super().__init__()
        self.model = model
        self.texts = texts
        self._report = None
        self._locations = ()
        self._searched = False
        self._preview = False
        layout = page_layout(self, "weather.page.title", "weather.page.subtitle", texts=texts)
        weather_page, search_page = QWidget(), QWidget()
        weather_layout, search_layout = QVBoxLayout(weather_page), QVBoxLayout(search_page)
        for inner in (weather_layout, search_layout):
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(16)
        self.sections = IslandPages((("weather.tab.current", weather_page), ("weather.tab.search", search_page)), floating=True, texts=texts)
        layout.addWidget(self.sections, 1)
        search_panel = QWidget()
        search_panel.setMaximumWidth(760)
        search_form = QVBoxLayout(search_panel)
        search_form.setContentsMargins(0, 0, 0, 0)
        search_form.setSpacing(10)
        search_layout.addWidget(search_panel)
        search_form.addWidget(text_label(texts, "weather.search.title", "SectionTitle"))
        search_form.addWidget(text_label(texts, "weather.search.hint", "Muted"))
        search_row = QHBoxLayout()
        self.query = QLineEdit(model.configuration.get("weather")["search_query"])
        texts.bind_text(self.query, "weather.search.placeholder", setter="setPlaceholderText")
        self.search = text_button(texts, "weather.search.button")
        self.search.clicked.connect(self._search)
        self.query.returnPressed.connect(self.search.click)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search)
        self.locations = QListWidget()
        self.locations.setObjectName("LocationResults")
        self.locations.setItemDelegate(NavigationDelegate(self.locations))
        self.locations.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.locations.setMaximumHeight(160)
        self.locations.itemClicked.connect(lambda item: self._select_location(self.locations.row(item)))
        self.locations.itemActivated.connect(lambda item: self._select_location(self.locations.row(item)))
        search_form.addLayout(search_row)
        search_form.addWidget(self.locations)
        self.search_status = plain_label(name="Muted")
        self.search_error = plain_label(name="Error")
        search_form.addWidget(self.search_status)
        search_form.addWidget(self.search_error)
        cancel_search = text_button(texts, "weather.search.cancel")
        cancel_search.clicked.connect(model.cancel)
        self.cancel_search = cancel_search
        search_form.addWidget(cancel_search, 0, Qt.AlignmentFlag.AlignLeft)

        actions = QHBoxLayout()
        self.status = plain_label(name="Muted")
        self.refresh = text_button(texts, "weather.refresh")
        self.refresh.setObjectName("Primary")
        self.refresh.clicked.connect(model.refresh)
        self.cancel = text_button(texts, "weather.cancel")
        self.cancel.clicked.connect(model.cancel)
        actions.addWidget(self.status, 1)
        actions.addWidget(self.refresh)
        actions.addWidget(self.cancel)
        weather_layout.addLayout(actions)
        self.error = plain_label(name="Error")
        weather_layout.addWidget(self.error)
        self.details = WeatherDetails(texts)
        weather_layout.addWidget(self.details, 1)
        self.search_details = WeatherDetails(texts)
        self.search_details.hide()
        search_layout.addWidget(self.search_details, 1)
        self.search_spacer = QWidget()
        search_layout.addWidget(self.search_spacer, 1)
        model.changed.connect(self.render)
        self.render(model.state)
        texts.changed.connect(self.retranslate)

    def retranslate(self):
        self.render(self.model.state)

    def _search(self):
        self._searched = True
        self._preview = False
        self.search_details.hide()
        self.search_spacer.show()
        self.model.search(self.query.text())
        self.render(self.model.state)

    def _select_location(self, index):
        if self.model.state.busy or not 0 <= index < len(self.model.state.locations):
            return
        self._preview = True
        self.search_details.show()
        self.search_spacer.hide()
        self.model.select_location(index)

    @Slot(object)
    def render(self, state: WeatherState) -> None:
        self.status.setText(self.texts.render(state.status))
        self.locations.setVisible(self._searched and bool(state.locations) and not state.searching)
        self.locations.setEnabled(not state.busy and not state.searching)
        self.search_status.setVisible(self._searched)
        if self._preview:
            message = self.texts.render(state.status)
        elif state.searching:
            message = self.texts.get("weather.search.running")
        elif state.error:
            message = self.texts.get("weather.search.failed")
        elif getattr(state.status, "key", "") == "weather.search.cancelled":
            message = self.texts.get("weather.search.cancelled")
        elif state.locations:
            message = self.texts.get("weather.search.results", count=len(state.locations))
        else:
            message = self.texts.get("weather.search.no_results")
        self.search_status.setText(message)
        self.search_error.setText(self.texts.render(state.error))
        self.search_error.setVisible(self._searched and bool(state.error))
        self.cancel_search.setVisible(state.searching)
        self.error.setText(self.texts.render(state.error))
        self.error.setVisible(bool(state.error))
        self.refresh.setEnabled(not state.busy)
        self.search.setEnabled(not state.searching)
        self.cancel.setEnabled(state.busy or state.searching)
        if state.locations != self._locations:
            self._locations = state.locations
            self.locations.clear()
            self.locations.addItems([location.name for location in state.locations])
            self.locations.setCurrentRow(-1)
            row_height = max(38, self.locations.sizeHintForRow(0))
            self.locations.setFixedHeight(min(160, row_height * max(1, len(state.locations)) + 12))
        self.details.render(state)
        self.search_details.render(state)
    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.model.set_active(True)

    def hideEvent(self, event) -> None:
        self.model.set_active(False)
        super().hideEvent(event)
