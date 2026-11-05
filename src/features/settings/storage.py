"""只管理本应用的用户文件；磁盘扫描与清理均在后台进行。"""

from src.shared.errors import error_message

from src.shared.errors import ui_error

from dataclasses import dataclass
from src.shared.messages import message
from datetime import datetime
import logging
from pathlib import Path
from threading import Event

from PySide6.QtCore import QSignalBlocker, QObject, Signal, Slot, QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget

from src.shared.paths import UserPaths
from src.shared.tasks import TaskRunner, check_cancelled
from src.shared.widgets import choice_box, data_table, plain_label, populate, text_button, text_label

LOGGER = logging.getLogger("workbench.storage")


@dataclass(frozen=True)
class StorageFile:
    name: str
    size: int
    modified: datetime


@dataclass(frozen=True)
class StorageSnapshot:
    rows: tuple[StorageFile, ...]
    count: int
    size: int


class StorageRepository:
    def __init__(self, paths: UserPaths, current_log: Path) -> None:
        self.directories = {"config": paths.config, "data": paths.data, "cache": paths.cache, "logs": paths.logs}
        self.current_log = current_log

    def _files(self, category: str, cancelled: Event):
        root = self.directories[category]
        for path in root.rglob("*"):
            check_cancelled(cancelled)
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(root.resolve()):
                yield path

    def inspect(self, category: str, cancelled: Event) -> StorageSnapshot:
        LOGGER.info("开始扫描本地文件：%s", category)
        root = self.directories[category]
        rows = []
        count = size = 0
        for path in self._files(category, cancelled):
            try:
                metadata = path.stat()
            except FileNotFoundError:
                continue
            count += 1
            size += metadata.st_size
            if len(rows) < 500:
                rows.append(StorageFile(str(path.relative_to(root)), metadata.st_size, datetime.fromtimestamp(metadata.st_mtime)))
        LOGGER.info("本地文件扫描完成：%s，%d 个文件，%d 字节", category, count, size)
        return StorageSnapshot(tuple(sorted(rows, key=lambda item: item.name)), count, size)

    def clear(self, category: str, cancelled: Event) -> StorageSnapshot:
        LOGGER.info("请求清理本地文件：%s", category)
        if category not in ("cache", "logs"):
            raise ui_error(ValueError, "errors.storage_clear")
        removed = 0
        for path in self._files(category, cancelled):
            if path == self.current_log or (category == "logs" and not path.name.startswith("session-")):
                continue
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                continue
        LOGGER.info("本地文件清理完成：%s，删除 %d 个文件", category, removed)
        return self.inspect(category, cancelled)


class StorageViewModel(QObject):
    changed = Signal(object, object, bool)

    def __init__(self, repository: StorageRepository, tasks: TaskRunner) -> None:
        super().__init__()
        self.repository, self.tasks = repository, tasks
        self.category = "config"
        self._generation = 0
        self._busy = False
        tasks.completed.connect(self._completed)

    @property
    def directory(self) -> Path:
        return self.repository.directories[self.category]

    def select(self, category: str) -> None:
        if self._busy:
            return
        self.category = category
        self.refresh()

    def refresh(self, clear: bool = False) -> None:
        if self._busy:
            return
        category = self.category
        action = self.repository.clear if clear else self.repository.inspect
        try:
            self._generation = self.tasks.submit("storage.files", lambda stop: action(category, stop))
        except RuntimeError as error:
            self.changed.emit(None, error_message(error), False)
            return
        self._busy = True
        self.changed.emit(None, message("storage.busy"), True)

    @Slot(str, int, object, object, bool)
    def _completed(self, key: str, generation: int, result: object, error: str, cancelled: bool) -> None:
        if key != "storage.files" or generation != self._generation:
            return
        self._busy = False
        if error:
            self.changed.emit(None, message("storage.cancelled") if cancelled else error, False)
        else:
            self.changed.emit(result, message("storage.summary", count=result.count, size=result.size / 1024), False)


class StorageView(QWidget):
    def __init__(self, model: StorageViewModel, texts) -> None:
        super().__init__()
        self.model = model
        self.texts = texts
        self._snapshot = None
        self._clear_dialog = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.category = choice_box()
        for key in model.repository.directories:
            self.category.addItem(texts.get("storage.category." + key), key)
        self.category.activated.connect(lambda: model.select(self.category.currentData()))
        open_button = text_button(texts, "storage.open")
        open_button.clicked.connect(self._open)
        self.refresh = text_button(texts, "storage.refresh")
        self.refresh.clicked.connect(lambda: model.refresh())
        self.clear = text_button(texts, "storage.clear")
        self.clear.clicked.connect(self._clear)
        row = QHBoxLayout()
        for item in (self.category, open_button, self.refresh, self.clear):
            row.addWidget(item)
        layout.addLayout(row)
        self.path = plain_label(str(model.directory), "Muted")
        self.status = text_label(texts, "storage.hint", "Muted")
        layout.addWidget(self.path)
        layout.addWidget(self.status)
        self.table = data_table(tuple(texts.get(key) for key in ("storage.file", "storage.size", "storage.modified")))
        layout.addWidget(self.table, 1)
        model.changed.connect(self.render)
        self.clear.setEnabled(False)
        texts.changed.connect(self.retranslate)

    def render(self, snapshot, message: str, busy: bool) -> None:
        self.path.setText(str(self.model.directory))
        self.texts.set_text(self.status, message)
        self.category.setEnabled(not busy)
        self.refresh.setEnabled(not busy)
        self.clear.setEnabled(not busy and self.model.category in ("cache", "logs"))
        if snapshot is not None:
            self._snapshot = snapshot
            self._render_rows()

    def _render_rows(self):
        if self._snapshot is not None:
            populate(self.table, tuple((item.name, self.texts.get("storage.kib", value=self.texts.number(item.size / 1024, 1)),
                self.texts.date(item.modified.date()) + " " + self.texts.time(item.modified, seconds=False)) for item in self._snapshot.rows))

    def retranslate(self):
        blocked = QSignalBlocker(self.category)
        for index in range(self.category.count()):
            self.category.setItemText(index, self.texts.get("storage.category." + self.category.itemData(index)))
        self.table.setHorizontalHeaderLabels([self.texts.get(key) for key in ("storage.file", "storage.size", "storage.modified")])
        if self._snapshot is not None:
            for row, item in enumerate(self._snapshot.rows):
                self.table.item(row, 1).setText(self.texts.get("storage.kib", value=self.texts.number(item.size / 1024, 1)))
                self.table.item(row, 2).setText(self.texts.date(item.modified.date()) + " " + self.texts.time(item.modified, seconds=False))

    def _open(self) -> None:
        LOGGER.info("请求打开本地文件目录：%s", self.model.category)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model.directory))):
            LOGGER.warning("系统无法打开本地文件目录")
            self.texts.bind_text(self.status, "storage.open_failed")

    def _clear(self) -> None:
        if self._clear_dialog is not None:
            self._clear_dialog.raise_()
            return
        category = self.model.category
        dialog = QMessageBox(self)
        self.texts.bind_text(dialog, "storage.clear_title", setter="setWindowTitle")
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        self.texts.bind_text(dialog, "storage.clear_cache" if category == "cache" else "storage.clear_logs")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        self.texts.bind_text(dialog.button(QMessageBox.StandardButton.Yes), "storage.confirm")
        self.texts.bind_text(dialog.button(QMessageBox.StandardButton.Cancel), "common.cancel")
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        self._clear_dialog = dialog
        dialog.finished.connect(lambda result: self._finish_clear(result, category))
        dialog.open()

    def _finish_clear(self, result, category):
        dialog, self._clear_dialog = self._clear_dialog, None
        if dialog:
            dialog.deleteLater()
        if result == QMessageBox.StandardButton.Yes and self.model.category == category:
            self.model.refresh(clear=True)
