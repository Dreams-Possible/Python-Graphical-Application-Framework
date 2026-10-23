"""只管理本应用的用户文件；磁盘扫描与清理均在后台进行。"""

from dataclasses import dataclass
from datetime import datetime
import logging
from pathlib import Path
from threading import Event

from PySide6.QtCore import QObject, Signal, Slot, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QComboBox, QHBoxLayout, QMessageBox, QPushButton, QVBoxLayout, QWidget

from src.shared.paths import UserPaths
from src.shared.tasks import TaskRunner, check_cancelled
from src.shared.widgets import choice_box, data_table, plain_label, populate

LOGGER = logging.getLogger("workbench.storage")


@dataclass(frozen=True)
class StorageSnapshot:
    rows: tuple[tuple[str, ...], ...]
    count: int
    size: int


class StorageRepository:
    def __init__(self, paths: UserPaths, current_log: Path) -> None:
        self.directories = {"配置": paths.config, "数据": paths.data, "缓存": paths.cache, "日志": paths.logs}
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
                rows.append((str(path.relative_to(root)), f"{metadata.st_size / 1024:.1f} KiB", datetime.fromtimestamp(metadata.st_mtime).strftime("%Y-%m-%d %H:%M")))
        LOGGER.info("本地文件扫描完成：%s，%d 个文件，%d 字节", category, count, size)
        return StorageSnapshot(tuple(sorted(rows)), count, size)

    def clear(self, category: str, cancelled: Event) -> StorageSnapshot:
        LOGGER.info("请求清理本地文件：%s", category)
        if category not in ("缓存", "日志"):
            raise ValueError("该类别不允许直接清理")
        removed = 0
        for path in self._files(category, cancelled):
            if path == self.current_log or (category == "日志" and not path.name.startswith("session-")):
                continue
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                continue
        LOGGER.info("本地文件清理完成：%s，删除 %d 个文件", category, removed)
        return self.inspect(category, cancelled)


class StorageViewModel(QObject):
    changed = Signal(object, str, bool)

    def __init__(self, repository: StorageRepository, tasks: TaskRunner) -> None:
        super().__init__()
        self.repository, self.tasks = repository, tasks
        self.category = "配置"
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
            self.changed.emit(None, str(error), False)
            return
        self._busy = True
        self.changed.emit(None, "正在处理本地文件…", True)

    @Slot(str, int, object, str, bool)
    def _completed(self, key: str, generation: int, result: object, error: str, cancelled: bool) -> None:
        if key != "storage.files" or generation != self._generation:
            return
        self._busy = False
        if error:
            self.changed.emit(None, "已取消" if cancelled else error, False)
        else:
            self.changed.emit(result, f"共 {result.count} 个文件，{result.size / 1024:.1f} KiB；最多展示 500 个", False)


class StorageView(QWidget):
    def __init__(self, model: StorageViewModel) -> None:
        super().__init__()
        self.model = model
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.category = choice_box()
        self.category.addItems(tuple(model.repository.directories))
        self.category.currentTextChanged.connect(model.select)
        open_button = QPushButton("打开目录")
        open_button.clicked.connect(self._open)
        self.refresh = QPushButton("刷新文件")
        self.refresh.clicked.connect(lambda: model.refresh())
        self.clear = QPushButton("清理文件")
        self.clear.clicked.connect(self._clear)
        row = QHBoxLayout()
        for item in (self.category, open_button, self.refresh, self.clear):
            row.addWidget(item)
        layout.addLayout(row)
        self.path = plain_label(str(model.directory), "Muted")
        self.status = plain_label("选择类别并刷新，查看此用户的文件。", "Muted")
        layout.addWidget(self.path)
        layout.addWidget(self.status)
        self.table = data_table(("文件", "大小", "更新时间"))
        layout.addWidget(self.table, 1)
        model.changed.connect(self.render)
        self.clear.setEnabled(False)

    def render(self, snapshot, message: str, busy: bool) -> None:
        self.path.setText(str(self.model.directory))
        self.status.setText(message)
        self.category.setEnabled(not busy)
        self.refresh.setEnabled(not busy)
        self.clear.setEnabled(not busy and self.model.category in ("缓存", "日志"))
        if snapshot is not None:
            populate(self.table, snapshot.rows)

    def _open(self) -> None:
        LOGGER.info("请求打开本地文件目录：%s", self.model.category)
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model.directory))):
            LOGGER.warning("系统无法打开本地文件目录")
            self.status.setText("系统无法打开该目录，可复制上方路径手动访问。")

    def _clear(self) -> None:
        text = "清理本应用的缓存文件？" if self.model.category == "缓存" else "清理本应用旧会话的日志？当前会话日志将保留。"
        if QMessageBox.question(self, "清理本地文件", text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
            self.model.refresh(clear=True)
