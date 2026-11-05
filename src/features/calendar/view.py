"""年、月、日共用日期状态；当前日期强调色，选中项仅描边。"""
from PySide6.QtCore import QDate, QPointF, Qt, QSignalBlocker
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QHBoxLayout, QPushButton,
    QStackedWidget, QStyledItemDelegate, QStyle, QTableWidget, QTableWidgetItem, QHeaderView, QWidget, QVBoxLayout)
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


class CalendarView(QWidget):
    def __init__(self, themes, texts, holidays=None):
        super().__init__()
        self.texts = texts
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
        self.group = QButtonGroup(self)
        self.modes = {}
        for key, label in (("year", "calendar.mode.year"), ("month", "calendar.mode.month"), ("day", "calendar.mode.day")):
            button = text_button(texts, label)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, value=key: self.set_mode(value))
            self.group.addButton(button)
            self.modes[key] = button
            controls.addWidget(button)
        controls.addWidget(today)
        self.retry = text_button(texts, "calendar.refresh")
        self.retry.clicked.connect(self.reload_holidays)
        self.retry.setVisible(holidays is not None)
        self.retry.setObjectName("CalendarAction")
        for index in range(controls.count()):
            button = controls.itemAt(index).widget()
            if isinstance(button, QPushButton) and button is not today:
                button.setObjectName("CalendarAction")
        layout.addLayout(controls)
        self.stack = QStackedWidget()
        self.year_grid = self.make_grid(3, 4)
        self.month_grid = self.make_grid(6, 7)
        self.month_grid.setHorizontalHeaderLabels([texts.weekday(day, short=True) for day in range(1, 8)])
        self.month_grid.horizontalHeader().show()
        self.stack.addWidget(self.year_grid)
        self.stack.addWidget(self.month_grid)
        day_page = QWidget()
        day_layout = QVBoxLayout(day_page)
        self.day_title = plain_label(name="CalendarDay")
        self.day_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.day_info = plain_label(name="SectionTitle")
        self.day_info.setAlignment(Qt.AlignmentFlag.AlignCenter)
        day_layout.addStretch()
        day_layout.addWidget(self.day_title)
        day_layout.addWidget(self.day_info)
        day_layout.addStretch()
        self.stack.addWidget(day_page)
        layout.addWidget(self.stack, 1)
        self.selected = plain_label(name="Muted")
        self.source_status = plain_label(name="Muted")
        layout.addWidget(self.selected)
        footer = QHBoxLayout()
        footer.addWidget(self.source_status, 1)
        footer.addWidget(self.retry)
        layout.addLayout(footer)
        self.previous.clicked.connect(lambda: self.step(-1))
        self.following.clicked.connect(lambda: self.step(1))
        today.clicked.connect(self.go_today)
        self.year_grid.currentCellChanged.connect(lambda row, col, *_: self.choose(self.year_grid, row, col))
        self.month_grid.currentCellChanged.connect(lambda row, col, *_: self.choose(self.month_grid, row, col))
        self.year_grid.cellDoubleClicked.connect(lambda *_: self.set_mode("month"))
        self.month_grid.cellDoubleClicked.connect(lambda *_: self.set_mode("day"))
        themes.changed.connect(self.retranslate)
        texts.changed.connect(self.retranslate)
        if holidays:
            holidays.changed.connect(self.refresh)
        self.refresh()

    def make_grid(self, rows, columns):
        grid = QTableWidget(rows, columns)
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

    def set_mode(self, mode):
        self.mode = mode
        self.shown = self.date
        self.refresh()

    def step(self, direction):
        self.shown = self.shown.addYears(direction) if self.mode == "year" else (self.shown.addMonths(direction) if self.mode == "month" else self.shown.addDays(direction))
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
        self.update_details()

    def update_details(self):
        weekday = self.texts.weekday(self.date.dayOfWeek())
        self.selected.setText(self.texts.get("calendar.date_weekday", date=self.texts.date(self.date), weekday=weekday))
        self.day_title.setText(self.texts.date(self.date, long=True))
        self.day_title.setProperty("current", self.date == self.today())
        self.day_title.style().unpolish(self.day_title)
        self.day_title.style().polish(self.day_title)
        self.day_info.setText(self.holiday_text(self.date))

    def retranslate(self):
        self.refresh(load_holidays=False)

    def refresh(self, load_holidays=True):
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
        grid = self.year_grid if self.mode == "year" else self.month_grid
        blocker = QSignalBlocker(grid)
        grid.clearSelection()
        grid.setCurrentCell(-1, -1)
        first = QDate(self.shown.year(), self.shown.month(), 1)
        start = first.addDays(1 - first.dayOfWeek())
        for i in range(grid.rowCount() * grid.columnCount()):
            day = QDate(self.shown.year(), i + 1, 1) if self.mode == "year" else start.addDays(i)
            text = self.texts.locale.standaloneMonthName(day.month()) if self.mode == "year" else self.texts.number(day.day())
            events = []
            if self.mode == "year" and self.holidays:
                names = []
                for n in range(1, day.daysInMonth() + 1):
                    event = self.holidays.event(QDate(day.year(), day.month(), n))
                    name = event.name if event else ""
                    if name and name not in names:
                        names.append(name)
                events = names
            if self.mode != "year" and self.holidays:
                event = self.holidays.label(day)
                if event:
                    events.append(self.texts.render(event))
            item = QTableWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole + 3, bool(events))
            item.setData(Qt.ItemDataRole.UserRole, day)
            item.setData(Qt.ItemDataRole.UserRole + 1, (day.year(), day.month()) == (today.year(), today.month()) if self.mode == "year" else day == today)
            item.setData(Qt.ItemDataRole.UserRole + 2, self.mode != "year" and day.month() != self.shown.month())
            item.setToolTip(day.toString("yyyy-MM" if self.mode == "year" else "yyyy-MM-dd") + "\n" + (" / ".join(events) if events else self.holiday_text(day)))
            row, column = divmod(i, grid.columnCount())
            grid.setItem(row, column, item)
            selected = (day.year(), day.month()) == (self.date.year(), self.date.month()) if self.mode == "year" else day == self.date
            if selected:
                grid.setCurrentCell(row, column)
        self.update_details()
        grid.viewport().update()

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()
