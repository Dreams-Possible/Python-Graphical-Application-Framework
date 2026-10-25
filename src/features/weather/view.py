"""天气详情与地点选择；纵向展示当前天气、小时趋势及每日预报。"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QListWidget, QAbstractItemView, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget

from src.shared.island import IslandPages
from src.features.weather.models import WeatherState
from src.features.weather.view_model import WeatherViewModel
from src.shared.widgets import NavigationDelegate, page_layout, plain_label
from src.features.weather.forecast_view import ForecastGraphic, WeatherSymbol


class WeatherDetails(QWidget):
    """当前天气与搜索页共同使用的天气详情。"""
    def __init__(self):
        super().__init__()
        self._report = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
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
        self.symbol = WeatherSymbol()
        self.summary = plain_label("尚无天气数据\n可搜索地点，或直接刷新默认地点。", "SectionTitle")
        self.summary.setWordWrap(True)
        card_layout.addWidget(self.temperature)
        card_layout.addWidget(self.symbol)
        card_layout.addSpacing(24)
        card_layout.addWidget(self.summary, 1)
        layout.addWidget(card)
        self.hours = ForecastGraphic(hourly=True)
        self.days = ForecastGraphic()
        self.history = ForecastGraphic()
        self.section_titles = []
        for title, graphic in (("未来 24 小时", self.hours), ("每日预报", self.days), ("历史 · 归档预报", self.history)):
            section = QFrame()
            section.setObjectName("Card")
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(20, 16, 20, 16)
            heading = plain_label(title, "SectionTitle")
            self.section_titles.append(heading)
            section_layout.addWidget(heading)
            if graphic.hourly:
                section_layout.addWidget(plain_label("温度趋势 · 降水概率 · 风速，左右滚动；点击列展开详情，再次点击收起", "Muted"))
            else:
                section_layout.addWidget(plain_label("最高 / 最低温度趋势 · 降水 · 风速，左右滚动；点击列展开详情，再次点击收起", "Muted"))
            scroller = QScrollArea()
            scroller.setWidgetResizable(True)
            scroller.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroller.setWidget(graphic)
            scroller.viewport().setAutoFillBackground(False)
            section_layout.addWidget(scroller)
            layout.addWidget(section)
        self.forecast_scrollers = content.findChildren(QScrollArea)
        self._resize_forecasts()
        source = QLabel('天气数据：<a href="https://open-meteo.com/">Open-Meteo</a> · CC BY 4.0 · 时间为地点当地时间')
        source.setProperty("themeRichText", source.text())
        source.setOpenExternalLinks(True)
        source.setObjectName("Muted")
        layout.addWidget(source)
        layout.addStretch()

    def render(self, state):
        if state.report == self._report:
            return
        self._report = state.report
        if state.report is None:
            self.temperature.setText("—")
            self.symbol.set_condition("")
            self.section_titles[1].setText("每日预报")
            self.section_titles[2].setText("历史 · 归档预报")
            self.summary.setText("尚无当前地点的天气数据")
            for table in (self.hours, self.days, self.history):
                table.set_rows(())
            self._resize_forecasts()
            return
        report = state.report
        self.temperature.setText(report.temperature)
        self.symbol.set_condition(report.condition)
        self.summary.setText(f"{report.location} · {report.condition}\n湿度 {report.humidity}   风速 {report.wind}\n{report.observed_at} · {report.timezone}")
        self.hours.set_rows(report.hourly, report.observed_at[5:13] + ":00")
        self.days.set_rows(report.daily, report.observed_at[:10])
        self.history.set_rows(report.history)
        self.section_titles[1].setText(f"每日预报 · {len(report.daily)} 天")
        self.section_titles[2].setText(f"历史 · {len(report.history)} 天归档")
        self._resize_forecasts()

    def _resize_forecasts(self):
        for scroller in self.forecast_scrollers:
            scroller.setFixedHeight(scroller.widget().height() + 18)




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
        self.sections = IslandPages((("当前天气", weather_page), ("搜索地点", search_page)), floating=True)
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
