"""天气详情与地点选择；表格仅在数据快照变化时重新填充。"""

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget

from src.features.weather.models import WeatherState
from src.features.weather.view_model import WeatherViewModel
from src.shared.widgets import choice_box, data_table, page_layout, plain_label, populate


class WeatherView(QWidget):
    def __init__(self, model: WeatherViewModel) -> None:
        super().__init__()
        self.model = model
        self._report = None
        self._locations = ()
        layout = page_layout(self, "天气", "当前条件、接下来 24 小时，以及更长的天气趋势。")
        search_row = QHBoxLayout()
        self.query = QLineEdit(model.configuration.get("weather")["search_query"])
        self.query.setPlaceholderText("搜索城市或地点，例如 上海、Tokyo")
        self.search = QPushButton("搜索地点")
        self.search.clicked.connect(lambda: model.search(self.query.text()))
        self.query.returnPressed.connect(self.search.click)
        search_row.addWidget(self.query, 1)
        search_row.addWidget(self.search)
        self.locations = choice_box()
        self.locations.setMinimumWidth(220)
        self.locations.setPlaceholderText("从搜索结果中选择地点")
        self.locations.activated.connect(model.select_location)
        search_row.addWidget(self.locations, 1)
        layout.addLayout(search_row)
        actions = QHBoxLayout()
        self.status = plain_label(name="Muted")
        self.refresh = QPushButton("刷新天气")
        self.refresh.setObjectName("Primary")
        self.refresh.clicked.connect(model.refresh)
        self.cancel = QPushButton("取消请求")
        self.cancel.clicked.connect(model.cancel)
        actions.addWidget(self.status, 1)
        actions.addWidget(self.refresh)
        actions.addWidget(self.cancel)
        layout.addLayout(actions)
        self.error = plain_label(name="Error")
        layout.addWidget(self.error)
        card = QFrame()
        card.setObjectName("Card")
        card_layout = QHBoxLayout(card)
        card_layout.setContentsMargins(24, 20, 24, 20)
        self.temperature = plain_label("—", "Temperature")
        self.summary = plain_label("尚无天气数据\n可搜索地点，或直接刷新默认地点。", "SectionTitle")
        card_layout.addWidget(self.temperature)
        card_layout.addSpacing(24)
        card_layout.addWidget(self.summary, 1)
        layout.addWidget(card)
        self.tabs = QTabWidget()
        self.hours = data_table(("当地时间", "天气", "温度", "体感", "湿度", "降水概率", "降水量", "风速"))
        self.days = data_table(("日期", "天气", "最低", "最高", "降水概率", "降水量", "最大风速"))
        self.history = data_table(("日期", "天气", "最低", "最高", "降水概率", "降水量", "最大风速"))
        self.tabs.addTab(self.hours, "未来 24 小时")
        self.tabs.addTab(self.days, "每日预报")
        self.tabs.addTab(self.history, "历史 · 归档预报")
        layout.addWidget(self.tabs, 1)
        source = QLabel('天气数据：<a href="https://open-meteo.com/">Open-Meteo</a> · CC BY 4.0 · 时间为地点当地时间')
        source.setOpenExternalLinks(True)
        source.setObjectName("Muted")
        layout.addWidget(source)
        model.changed.connect(self.render)
        self.render(model.state)

    @Slot(object)
    def render(self, state: WeatherState) -> None:
        self.status.setText(state.status)
        self.error.setText(state.error)
        self.error.setVisible(bool(state.error))
        self.refresh.setEnabled(not state.busy)
        self.search.setEnabled(not state.searching)
        self.cancel.setEnabled(state.busy or state.searching)
        if state.locations != self._locations:
            self._locations = state.locations
            self.locations.clear()
            self.locations.addItems([location.name for location in state.locations])
            self.locations.setCurrentIndex(-1)
        if state.report == self._report:
            return
        self._report = state.report
        if state.report is None:
            self.temperature.setText("—")
            self.summary.setText("尚无当前地点的天气数据")
            for table in (self.hours, self.days, self.history):
                table.setRowCount(0)
            return
        report = state.report
        self.temperature.setText(report.temperature)
        self.summary.setText(f"{report.location} · {report.condition}\n湿度 {report.humidity}   风速 {report.wind}\n{report.observed_at} · {report.timezone}")
        populate(self.hours, report.hourly)
        populate(self.days, report.daily)
        populate(self.history, report.history)
        self.tabs.setTabText(1, f"每日预报 · {len(report.daily)} 天")
        self.tabs.setTabText(2, f"历史 · {len(report.history)} 天归档")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.model.set_active(True)

    def hideEvent(self, event) -> None:
        self.model.set_active(False)
        super().hideEvent(event)
