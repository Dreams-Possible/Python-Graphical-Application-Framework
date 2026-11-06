"""年、月、日共用日期状态；当前日期强调色，选中项仅描边。"""
from PySide6.QtCore import QDate, QPointF, Qt, QSignalBlocker
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QSizePolicy, QAbstractItemView, QBoxLayout, QButtonGroup, QHBoxLayout, QPushButton,
    QStackedWidget, QStyledItemDelegate, QStyle, QTableWidget, QTableWidgetItem, QHeaderView, QWidget, QVBoxLayout)
from src.shared.gestures import KineticScrollArea, PeriodSwipePages, SwipeTableWidget
from src.features.calendar.history_view import HistoryEventsView
from src.shared.widgets import page_layout, plain_label, text_button


class DateDelegate(QStyledItemDelegate):
    def __init__(self, themes, parent):
        super().__init__(parent)
        self.themes = themes

    def paint(self, painter, option, index):
        colors = self.themes.colors
        rect = option.rect.adjusted(4, 4, -4, -4)
        current = bool(index.data(Qt.ItemDataRole.UserRole + 1))
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        muted = bool(index.data(Qt.ItemDataRole.UserRole + 2))
        painter.save()
        # 覆盖平台样式预绘制的选中强调条，只保留本组件的圆角边框。
        painter.setClipRect(option.rect)
        painter.fillRect(option.rect, QColor(colors["surface"]))
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["selected" if current else "surface"]))
        painter.drawRoundedRect(rect, 9, 9)
        if selected:
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(colors["accent"]), 2))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 9, 9)
        painter.setPen(QColor(colors["accent" if current else ("muted" if muted else "text")]))
        painter.drawText(rect.adjusted(4, 2, -4, -2), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, index.data() or "")
        if index.data(Qt.ItemDataRole.UserRole + 3):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors["accent"]))
            painter.drawEllipse(QPointF(rect.right() - 9, rect.top() + 9), 2.5, 2.5)
        painter.restore()


class CalendarDayPage(KineticScrollArea):
    """日期面板只负责内容；滑动由公共周期容器处理，预览不发起请求。"""
    def __init__(self, texts, history=None, preview=False):
        super().__init__()
        self.texts = texts
        self.day = None
        content = QWidget()
        self.setWidget(content)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        self.title = plain_label(name="CalendarDay")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info = plain_label(name="SectionTitle")
        self.info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        layout.addWidget(self.info)
        self.history_view = None
        if preview:
            hint = plain_label(name="Muted")
            hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
            texts.bind_text(hint, "calendar.day_preview")
            layout.addWidget(hint)
        else:
            self.history_view = HistoryEventsView(texts, history)
            layout.addWidget(self.history_view)
        layout.addStretch()

    def set_day(self, day, today, holiday):
        changed = self.day != day
        self.day = QDate(day)
        self.title.setText(self.texts.date(day, long=True))
        self.title.setProperty("current", day == today)
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)
        self.info.setText(holiday)
        if self.history_view:
            self.history_view.set_day(day)
        if changed:
            self.verticalScrollBar().setValue(0)


class CalendarView(QWidget):
    def __init__(self, themes, texts, holidays=None, history=None):
        super().__init__()
        self.texts = texts
        self.history = history
        self.themes, self.holidays = themes, holidays
        self.date = self.today()
        self.mode = "month"
        self.shown = self.date
        layout = page_layout(self, "calendar.page.title", "calendar.page.subtitle", texts=texts)
        controls = QHBoxLayout()
        self.previous = QPushButton()
        self.following = QPushButton()
        self.title = plain_label(name="SectionTitle")
        today = text_button(texts, "common.today")
        today.setObjectName("Primary")
        controls.addWidget(self.previous)
        controls.addWidget(self.following)
        controls.addWidget(self.title, 1)
        actions = QHBoxLayout()
        self.group = QButtonGroup(self)
        self.modes = {}
        for key, label in (("year", "calendar.mode.year"), ("month", "calendar.mode.month"), ("day", "calendar.mode.day")):
            button = text_button(texts, label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=key: self.set_mode(value))
            self.group.addButton(button)
            self.modes[key] = button
            actions.addWidget(button)
        actions.addWidget(today)
        self.today_button = today
        self.retry = text_button(texts, "calendar.refresh")
        self.retry.clicked.connect(self.reload_holidays)
        self.retry.setVisible(holidays is not None)
        self.retry.setObjectName("CalendarAction")
        actions.addWidget(self.retry)
        for item in [controls.itemAt(i) for i in range(controls.count())] + [actions.itemAt(i) for i in range(actions.count())]:
            button = item.widget()
            if isinstance(button, QPushButton) and button is not today:
                button.setObjectName("CalendarAction")
        controls.setContentsMargins(0, 0, 0, 0)
        actions.setContentsMargins(0, 0, 0, 0)
        self._toolbar_left, self._toolbar_right = QWidget(), QWidget()
        self._toolbar_left.setLayout(controls)
        self._toolbar_right.setLayout(actions)
        self._toolbar_right.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Preferred)
        toolbar = QWidget()
        self._toolbar_layout = QBoxLayout(QBoxLayout.Direction.LeftToRight, toolbar)
        self._toolbar_layout.setContentsMargins(0, 0, 0, 0)
        self._toolbar_layout.addWidget(self._toolbar_left, 1)
        self._toolbar_layout.addWidget(self._toolbar_right)
        self._toolbar_layout.setAlignment(self._toolbar_right, Qt.AlignmentFlag.AlignRight)
        layout.addWidget(toolbar)
        self.stack = QStackedWidget()
        self.year_pages = self.make_period_pages("year", 3, 4)
        self.month_pages = self.make_period_pages("month", 6, 7)
        self.year_grid = self.year_pages.pages[1]
        self.month_grid = self.month_pages.pages[1]
        self.stack.addWidget(self.year_pages)
        self.stack.addWidget(self.month_pages)
        day_panels = [CalendarDayPage(texts, history if index == 1 else None, preview=index != 1) for index in range(3)]
        self.day_pages = PeriodSwipePages(day_panels)
        self.day_pages.stepRequested.connect(self.step)
        self.day_title = day_panels[1].title
        self.day_info = day_panels[1].info
        self.history_view = day_panels[1].history_view
        self.history_view.refreshRequested.connect(lambda: self._load_history(force=True))
        self.stack.addWidget(self.day_pages)
        layout.addWidget(self.stack, 1)
        self.selected = plain_label(name="Muted")
        self.source_status = plain_label(name="Muted")
        layout.addWidget(self.selected)
        footer = QHBoxLayout()
        footer.addWidget(self.source_status, 1)
        layout.addLayout(footer)
        self.previous.clicked.connect(lambda: self.step(-1))
        self.following.clicked.connect(lambda: self.step(1))
        today.clicked.connect(self.go_today)
        themes.changed.connect(self.retranslate)
        texts.changed.connect(self.retranslate)
        if holidays:
            holidays.changed.connect(self.refresh)
        self.refresh()

    def make_grid(self, rows, columns):
        grid = SwipeTableWidget(rows, columns)
        grid.setObjectName("CalendarGrid")
        grid.setShowGrid(False)
        grid.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        grid.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        grid.setItemDelegate(DateDelegate(self.themes, grid))
        grid.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        grid.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        grid.horizontalHeader().hide()
        grid.verticalHeader().hide()
        return grid

    def make_period_pages(self, mode, rows, columns):
        grids = [self.make_grid(rows, columns) for _ in range(3)]
        for grid in grids:
            if mode == "month":
                grid.horizontalHeader().show()
            grid.currentCellChanged.connect(lambda row, column, *_, source=grid: self.choose(source, row, column))
            grid.cellDoubleClicked.connect(lambda *_, target="month" if mode == "year" else "day": self.set_mode(target))
        pages = PeriodSwipePages(grids)
        pages.stepRequested.connect(self.step)
        return pages

    def _arrange_toolbar(self):
        if not hasattr(self, "_toolbar_layout"):
            return
        available = self.width() - 2 * self.layout().contentsMargins().left()
        required = self._toolbar_left.sizeHint().width() + self._toolbar_right.sizeHint().width() + self._toolbar_layout.spacing()
        self._toolbar_layout.setDirection(QBoxLayout.Direction.TopToBottom if required > available else QBoxLayout.Direction.LeftToRight)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange_toolbar()

    def set_mode(self, mode):
        self.mode = mode
        self.shown = self.date
        self.refresh()

    def step(self, direction):
        self.year_pages.reset_period()
        self.month_pages.reset_period()
        self.day_pages.reset_period()
        candidate = self.shown.addYears(direction) if self.mode == "year" else (self.shown.addMonths(direction) if self.mode == "month" else self.shown.addDays(direction))
        if not candidate.isValid() or not 1 <= candidate.year() <= 9999:
            self.refresh()
            return
        self.shown = candidate
        if self.mode == "day":
            self.date = self.shown
        self.refresh()

    def reload_holidays(self):
        if self.holidays:
            self.holidays.retry(self.shown.year())

    def today(self):
        return self.holidays.today() if self.holidays else QDate.currentDate()

    def go_today(self):
        self.date = self.shown = self.today()
        self.refresh()

    def holiday_text(self, date):
        return self.texts.render(self.holidays.text(date)) if self.holidays else self.texts.get("calendar.unconfigured")

    def choose(self, grid, row, column):
        item = grid.item(row, column)
        if item is None:
            return
        self.date = item.data(Qt.ItemDataRole.UserRole)
        self._sync_period_selection(grid)
        self.update_details()

    def _sync_period_selection(self, source):
        for pager, mode in ((self.year_pages, "year"), (self.month_pages, "month")):
            for grid in pager.pages:
                if grid is source:
                    continue
                blocker = QSignalBlocker(grid)
                grid.clearSelection()
                grid.setCurrentCell(-1, -1)
                for row in range(grid.rowCount()):
                    for column in range(grid.columnCount()):
                        item = grid.item(row, column)
                        if item is None:
                            continue
                        day = item.data(Qt.ItemDataRole.UserRole)
                        selected = (day.year(), day.month()) == (self.date.year(), self.date.month()) if mode == "year" else day == self.date
                        if selected:
                            grid.setCurrentCell(row, column)
                del blocker

    def update_details(self):
        weekday = self.texts.weekday(self.date.dayOfWeek())
        self.selected.setText(self.texts.get("calendar.date_weekday", date=self.texts.date(self.date), weekday=weekday))
        for offset, panel in zip((-1, 0, 1), self.day_pages.pages):
            day = self.date.addDays(offset)
            if not day.isValid() or not 1 <= day.year() <= 9999:
                day = self.date
            panel.set_day(day, self.today(), self.holiday_text(day))

    def retranslate(self):
        self.refresh(load_holidays=False, load_history=False)

    def refresh(self, load_holidays=True, load_history=True):
        self.month_grid.setHorizontalHeaderLabels([self.texts.weekday(day, short=True) for day in range(1, 8)])
        today = self.today()
        self.modes[self.mode].setChecked(True)
        self.stack.setCurrentIndex({"year": 0, "month": 1, "day": 2}[self.mode])
        self.previous.setText(self.texts.get("calendar.previous." + self.mode))
        self.following.setText(self.texts.get("calendar.next." + self.mode))
        self.title.setText(self.texts.get("calendar.year_title", year=self.shown.year()) if self.mode == "year" else self.texts.locale.toString(self.shown, self.texts.get("calendar.month_pattern")))
        current = self.shown.year() == today.year() and (self.mode == "year" or self.shown.month() == today.month())
        self.title.setProperty("current", current)
        self.title.style().unpolish(self.title)
        self.title.style().polish(self.title)
        if self.holidays:
            if load_holidays:
                self.holidays.ensure(self.shown.year())
            self.source_status.setText(self.texts.render(self.holidays.status(self.shown.year())))
        for pager in (self.year_pages, self.month_pages, self.day_pages):
            pager.reset_period()
        if self.mode in ("year", "month"):
            pager = self.year_pages if self.mode == "year" else self.month_pages
            for offset, grid in zip((-1, 0, 1), pager.pages):
                shown = self.shown.addYears(offset) if self.mode == "year" else self.shown.addMonths(offset)
                if not shown.isValid() or not 1 <= shown.year() <= 9999:
                    shown = self.shown
                self.populate_period(grid, shown, self.mode)
        self.update_details()
        self.history_view.set_day(self.date)
        self._arrange_toolbar()
        if load_history:
            self._load_history()

    def populate_period(self, grid, shown, mode):
        today = self.today()
        if mode == "month":
            grid.setHorizontalHeaderLabels([self.texts.weekday(day, short=True) for day in range(1, 8)])
        blocker = QSignalBlocker(grid)
        grid.clearSelection()
        grid.setCurrentCell(-1, -1)
        first = QDate(shown.year(), shown.month(), 1)
        start = first.addDays(1 - first.dayOfWeek())
        for i in range(grid.rowCount() * grid.columnCount()):
            day = QDate(shown.year(), i + 1, 1) if mode == "year" else start.addDays(i)
            text = self.texts.locale.standaloneMonthName(day.month()) if mode == "year" else self.texts.number(day.day())
            events = []
            if mode == "year" and self.holidays:
                names = []
                for n in range(1, day.daysInMonth() + 1):
                    event = self.holidays.event(QDate(day.year(), day.month(), n))
                    name = event.name if event else ""
                    if name and name not in names:
                        names.append(name)
                events = names
            if mode != "year" and self.holidays:
                event = self.holidays.label(day)
                if event:
                    events.append(self.texts.render(event))
            item = QTableWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole + 3, bool(events))
            item.setData(Qt.ItemDataRole.UserRole, day)
            item.setData(Qt.ItemDataRole.UserRole + 1, (day.year(), day.month()) == (today.year(), today.month()) if mode == "year" else day == today)
            item.setData(Qt.ItemDataRole.UserRole + 2, mode != "year" and day.month() != shown.month())
            item.setToolTip(day.toString("yyyy-MM" if mode == "year" else "yyyy-MM-dd") + "\n" + (" / ".join(events) if events else self.holiday_text(day)))
            row, column = divmod(i, grid.columnCount())
            grid.setItem(row, column, item)
            selected = (day.year(), day.month()) == (self.date.year(), self.date.month()) if mode == "year" else day == self.date
            if selected:
                grid.setCurrentCell(row, column)
        grid.viewport().update()

    def _load_history(self, force=False):
        if self.history is None:
            return
        if self.mode == "day" and self.isVisible():
            self.history.load(self.date.toPython(), force=force)
        else:
            self.history.suspend()

    def hideEvent(self, event):
        if self.history:
            self.history.suspend()
        super().hideEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
