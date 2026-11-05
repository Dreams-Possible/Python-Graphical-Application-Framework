import logging

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence, QShortcut
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QMessageBox, QPushButton, QSizePolicy, QAbstractItemView, QApplication, QHeaderView, QTableView, QWidget

from src.features.logs.view_model import LogsViewModel
from src.features.logs.table_model import LogTableModel
from src.shared.widgets import NavigationDelegate, choice_box, page_layout, plain_label, text_button, text_label
from src.shared.theme import ThemeManager


class LogsView(QWidget):
    def __init__(self, model: LogsViewModel, themes: ThemeManager, texts) -> None:
        super().__init__()
        self.model = model
        self.texts = texts
        self._session_names = ()
        self.themes = themes
        self._clear_dialog = None
        layout = page_layout(self, "logs.page.title", "logs.page.subtitle", texts=texts)
        files = QHBoxLayout()
        self.sessions = choice_box()
        self.sessions.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sessions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sessions.setMinimumContentsLength(20)
        self.sessions.addItem(self.texts.get("logs.live"), "")
        self.sessions.activated.connect(lambda: model.select_session(self.sessions.currentData()))
        self.refresh_files = text_button(texts, "logs.refresh")
        self.refresh_files.clicked.connect(model.list_files)
        open_folder = text_button(texts, "logs.open")
        open_folder.clicked.connect(self._open_folder)
        self.clear_files = text_button(texts, "logs.clear_all")
        self.clear_files.setObjectName("Danger")
        texts.bind_text(self.clear_files, "logs.clear_all_hint", setter="setToolTip")
        self.clear_files.clicked.connect(self._confirm_clear)
        files.addWidget(self.sessions, 1)
        files.addWidget(self.refresh_files)
        files.addWidget(open_folder)
        files.addWidget(self.clear_files)
        layout.addLayout(files)
        self.file_status = text_label(texts, "logs.path", "Muted", path=str(model.service.path.parent))
        layout.addWidget(self.file_status)
        actions = QHBoxLayout()
        self.level = choice_box()
        for key in ("ALL", "DEBUG", "INFO", "WARNING", "ERROR"):
            self.level.addItem(texts.get("logs.level." + key), key)
        self.level.activated.connect(lambda: model.set_filter(self.level.currentData()))
        self.follow = QCheckBox()
        texts.bind_text(self.follow, "logs.follow")
        self.follow.setChecked(True)
        clear = text_button(texts, "logs.clear_view")
        texts.bind_text(clear, "logs.clear_view_hint", setter="setToolTip")
        clear.clicked.connect(model.clear)
        actions.addWidget(self.level)
        actions.addStretch()
        actions.addWidget(self.follow)
        actions.addWidget(clear)
        layout.addLayout(actions)
        self.console = QTableView()
        self.table_model = LogTableModel(themes, model.configuration.get("logging")["maximum_lines"], texts, self)
        self.console.setModel(self.table_model)
        self.console.setItemDelegate(NavigationDelegate(self.console))
        self.console.setAlternatingRowColors(True)
        self.console.setShowGrid(False)
        self.console.setWordWrap(False)
        self.console.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.console.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.console.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerItem)
        self.console.verticalHeader().hide()
        self.console.verticalHeader().setDefaultSectionSize(32)
        header = self.console.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for column, width in enumerate((90, 180, 210, 260)):
            self.console.setColumnWidth(column, width)
        texts.bind_text(self.console, "logs.table_hint", setter="setToolTip")
        copy = QShortcut(QKeySequence.StandardKey.Copy, self.console)
        copy.activated.connect(self._copy_rows)
        layout.addWidget(self.console, 1)
        model.appended.connect(self.append)
        model.replaced.connect(self.replace)
        model.limit_changed.connect(self.table_model.set_limit)
        self.follow.toggled.connect(lambda checked: self.console.scrollToBottom() if checked else None)
        model.files_changed.connect(self._files_changed)
        model.management_changed.connect(self._management_changed)
        texts.changed.connect(self.retranslate)

    def retranslate(self):
        blocker = QSignalBlocker(self.level)
        for index in range(self.level.count()):
            self.level.setItemText(index, self.texts.get("logs.level." + self.level.itemData(index)))
        self._files_changed(self._session_names)

    def _files_changed(self, names) -> None:
        self._session_names = tuple(names)
        self.sessions.blockSignals(True)
        self.sessions.clear()
        self.sessions.addItem(self.texts.get("logs.live"), "")
        for name in names:
            self.sessions.addItem(name, name)
        if self.model.history_name and self.sessions.findData(self.model.history_name) < 0:
            self.sessions.addItem(self.texts.get("logs.missing_history", name=self.model.history_name), self.model.history_name)
        self.sessions.setCurrentIndex(max(0, self.sessions.findData(self.model.history_name)))
        self.sessions.blockSignals(False)

    def _management_changed(self, message: str, busy: bool, name: str) -> None:
        self.texts.set_text(self.file_status, message)
        for widget in (self.sessions, self.refresh_files, self.clear_files):
            widget.setEnabled(not busy)
        self.follow.setEnabled(not name)
        if not busy:
            self.sessions.setCurrentIndex(max(0, self.sessions.findData(name)))

    def _open_folder(self) -> None:
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model.service.path.parent)))
        self.texts.bind_text(self.file_status, "logs.open_done" if opened else "logs.open_failed", path=str(self.model.service.path.parent))
        logging.getLogger("workbench.logs").info("打开日志目录：%s", "已交给系统" if opened else "失败")

    def _confirm_clear(self) -> None:
        if self._clear_dialog is not None:
            self._clear_dialog.raise_()
            return
        dialog = QMessageBox(self)
        self.texts.bind_text(dialog, "logs.clear_all", setter="setWindowTitle")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        self.texts.bind_text(dialog, "logs.clear_prompt")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        self.texts.bind_text(dialog.button(QMessageBox.StandardButton.Yes), "logs.confirm_clear")
        self.texts.bind_text(dialog.button(QMessageBox.StandardButton.Cancel), "common.cancel")
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        self._clear_dialog = dialog
        dialog.finished.connect(self._finish_clear)
        dialog.open()

    def _finish_clear(self, result: int) -> None:
        dialog, self._clear_dialog = self._clear_dialog, None
        if dialog:
            dialog.deleteLater()
        if result == QMessageBox.StandardButton.Yes:
            self.model.clear_all_files()

    def _copy_rows(self) -> None:
        rows = sorted(index.row() for index in self.console.selectionModel().selectedRows())
        entries = [self.table_model.entries[row] for row in rows]
        if entries:
            QApplication.clipboard().setText("\n".join("\t".join((entry.level, entry.timestamp, entry.source, entry.message)) for entry in entries))

    def replace(self, entries: tuple) -> None:
        previous = self.console.verticalScrollBar().value()
        self.table_model.replace(entries)
        if self.follow.isChecked():
            self.console.scrollToBottom()
        else:
            self.console.verticalScrollBar().setValue(previous)

    def append(self, entries: tuple) -> None:
        previous = self.console.verticalScrollBar().value()
        removed = self.table_model.append(entries)
        if self.follow.isChecked():
            self.console.scrollToBottom()
        else:
            self.console.verticalScrollBar().setValue(max(0, previous - removed))

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.model.set_active(True)
        self.model.list_files()

    def hideEvent(self, event) -> None:
        self.model.set_active(False)
        super().hideEvent(event)
