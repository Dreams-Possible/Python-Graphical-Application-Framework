"""日志缓冲与界面刷新解耦；隐藏页继续收集但不发布界面状态。"""

from collections import deque
import logging

LOGGER = logging.getLogger("workbench.logs")

from PySide6.QtCore import QObject, QTimer, Signal

from src.shared.configuration import Configuration
from src.shared.logging_service import LoggingService
from src.features.logs.repository import LogRepository


class LogsViewModel(QObject):
    appended = Signal(object)
    replaced = Signal(object)
    limit_changed = Signal(int)
    files_changed = Signal(object)
    management_changed = Signal(str, bool, str)

    def __init__(self, service: LoggingService, configuration: Configuration, tasks) -> None:
        super().__init__()
        self.service, self.configuration = service, configuration
        self.tasks = tasks
        self.repository = LogRepository(service)
        self.history_name = ""
        self._history = ()
        self._busy = False
        self._generation = -1
        self._operation = ""
        tasks.completed.connect(self._completed)
        self._entries = deque(maxlen=configuration.get("logging")["maximum_lines"])
        self._active = False
        self._level = "ALL"
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._flush)
        configuration.changed.connect(self._configured)
        self._configured("logging")

    def _configured(self, module: str) -> None:
        if module != "logging":
            return
        values = self.configuration.get("logging")
        self.service.configure(values)
        self._entries = deque(self._entries, maxlen=values["maximum_lines"])
        self._timer.start(values["flush_ms"])
        self.limit_changed.emit(values["maximum_lines"])
        if self._active:
            self.replaced.emit(self._visible())

    def _matches(self, entry) -> bool:
        return self._level == "ALL" or entry.level == self._level or (self._level == "ERROR" and entry.level == "CRITICAL")

    def _visible(self) -> tuple:
        entries = self._history if self.history_name else self._entries
        limit = self.configuration.get("logging")["maximum_lines"]
        return tuple(entry for entry in entries if self._matches(entry))[-limit:]

    def _flush(self) -> None:
        entries = self.service.buffer.drain()
        self._entries.extend(entries)
        if self._active and entries and not self.history_name:
            self.appended.emit(tuple(entry for entry in entries if self._matches(entry)))

    def set_active(self, active: bool) -> None:
        self._active = False
        self._flush()
        self._active = active
        if active:
            self.replaced.emit(self._visible())

    def set_filter(self, level: str) -> None:
        LOGGER.info("日志视图筛选切换：%s", level)
        self._level = level
        self.replaced.emit(self._visible())

    def clear(self) -> None:
        if self.history_name:
            self._history = ()
        else:
            self.service.buffer.drain()
            self._entries.clear()
        self.replaced.emit(())
        LOGGER.info("用户清空日志视图，文件日志保留")

    def refresh_view(self) -> None:
        if self._active:
            self.replaced.emit(self._visible())

    def stop(self) -> None:
        self._timer.stop()

    def list_files(self) -> None:
        self._submit("list", self.repository.files)

    def select_session(self, name: str) -> None:
        if self._busy:
            return
        if not name:
            self.history_name = ""
            self._history = ()
            self.refresh_view()
            self.management_changed.emit("正在查看本次运行的实时日志", False, "")
            return
        limit = self.configuration.get("logging")["maximum_lines"]
        self._submit("read", lambda stop: self.repository.read(name, limit, stop))

    def clear_all_files(self) -> None:
        self._submit("clear", self.repository.clear_all)

    def _submit(self, operation, function) -> None:
        if self._busy:
            return
        try:
            self._generation = self.tasks.submit("logs.files", function)
        except RuntimeError as error:
            self.management_changed.emit(str(error), False, self.history_name)
            return
        self._operation, self._busy = operation, True
        self.management_changed.emit("正在处理日志文件…", True, self.history_name)
        LOGGER.info("日志文件操作开始：%s", operation)

    def _completed(self, key, generation, result, error, cancelled) -> None:
        if key != "logs.files" or generation != self._generation:
            return
        self._busy = False
        if error or cancelled:
            self.management_changed.emit("操作未完成（清理可能已部分执行）：" + error, False, self.history_name)
            return
        if self._operation == "list":
            self.files_changed.emit(result)
            message = f"找到 {len(result)} 个历史日志文件"
        elif self._operation == "read":
            self.history_name, self._history = result.name, result.entries
            self.refresh_view()
            message = f"历史日志：{result.name} · {len(result.entries)} 行"
            if result.limited:
                message += " · 仅展示末尾部分，完整内容请打开文件查看"
        else:
            removed, failures = result
            self.history_name, self._history = "", ()
            self._entries.clear()
            self._flush()
            self.refresh_view()
            self.files_changed.emit(tuple(name for name in failures if name != self.service.path.name))
            message = f"已删除 {removed} 个历史文件；当前日志继续记录，无法撤销。"
            if failures:
                message += "未清除文件：" + "、".join(failures) + "。请刷新列表重试。"
        LOGGER.info("日志文件操作结束：%s", self._operation)
        self.management_changed.emit(message, False, self.history_name)
