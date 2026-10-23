"""天气详情与地点选择；表格仅在数据快照变化时重新填充。"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QListWidget, QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget

from src.shared.island import IslandPages
from src.features.weather.models import WeatherState
from src.features.weather.view_model import WeatherViewModel
from src.shared.widgets import NavigationDelegate, data_table, page_layout, plain_label, populate


class WeatherDetails(QWidget):
    """当前天气与搜索页共同使用的天气详情。"""
    def __init__(self):
        super().__init__()
        self._report = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(16)
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
        source.setProperty("themeRichText", source.text())
        source.setOpenExternalLinks(True)
        source.setObjectName("Muted")
        layout.addWidget(source)

    def render(self, state):
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



class WeatherView(QWidget):
    def __init__(self, model: WeatherViewModel) -> None:
        super().__init__()
        self.model = model
        self._report = None
        self._locations = ()
        self._searched = False
        self._preview = False
        layout = page_layout(self, "天气", "当前条件、接下来 24 小时，以及更长的天气趋势。")
        weather_page, search_page = QWidget(), QWidget()
        weather_layout, search_layout = QVBoxLayout(weather_page), QVBoxLayout(search_page)
        for inner in (weather_layout, search_layout):
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(16)
        self.sections = IslandPages((("当前天气", weather_page), ("搜索地点", search_page)))
        layout.addWidget(self.sections, 1)
        search_panel = QWidget()
        search_panel.setMaximumWidth(760)
        search_form = QVBoxLayout(search_panel)
        search_form.setContentsMargins(0, 0, 0, 0)
        search_form.setSpacing(10)
        search_layout.addWidget(search_panel)
        search_form.addWidget(plain_label("查找城市", "SectionTitle"))
        search_form.addWidget(plain_label("输入城市名称，选择搜索结果后查看该地区天气。", "Muted"))
        search_row = QHBoxLayout()
        self.query = QLineEdit(model.configuration.get("weather")["search_query"])
        self.query.setPlaceholderText("搜索城市或地点，例如 上海、Tokyo")
        self.search = QPushButton("搜索地点")
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
        cancel_search = QPushButton("取消搜索")
        cancel_search.clicked.connect(model.cancel)
        self.cancel_search = cancel_search
        search_form.addWidget(cancel_search, 0, Qt.AlignmentFlag.AlignLeft)

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
        weather_layout.addLayout(actions)
        self.error = plain_label(name="Error")
        weather_layout.addWidget(self.error)
        self.details = WeatherDetails()
        weather_layout.addWidget(self.details, 1)
        self.search_details = WeatherDetails()
        self.search_details.hide()
        search_layout.addWidget(self.search_details, 1)
        self.search_spacer = QWidget()
        search_layout.addWidget(self.search_spacer, 1)
        model.changed.connect(self.render)
        self.render(model.state)

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
        self.status.setText(state.status)
        self.locations.setVisible(self._searched and bool(state.locations) and not state.searching)
        self.locations.setEnabled(not state.busy and not state.searching)
        self.search_status.setVisible(self._searched)
        if self._preview:
            message = state.status
        elif state.searching:
            message = "正在搜索…"
        elif state.error:
            message = "搜索未完成，请修改关键词或重试。"
        elif state.status == "地点搜索已取消":
            message = "搜索已取消。"
        elif state.locations:
            message = f"找到 {len(state.locations)} 个地点，点击查看天气。"
        else:
            message = "未找到匹配地点，请换一个名称重试。"
        self.search_status.setText(message)
        self.search_error.setText(state.error)
        self.search_error.setVisible(self._searched and bool(state.error))
        self.cancel_search.setVisible(state.searching)
        self.error.setText(state.error)
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
