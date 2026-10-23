"""标准日志入口与有界批量 UI 缓冲，不在工作线程操作 Qt 控件。"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
import logging
import os
from pathlib import Path
from threading import Lock


@dataclass(frozen=True)
class LogEntry:
    timestamp: str
    level: str
    source: str
    message: str


class _BufferHandler(logging.Handler):
    def __init__(self, capacity: int = 10000) -> None:
        super().__init__()
        self.entries: deque[LogEntry] = deque(maxlen=capacity)
        self.buffer_lock = Lock()
        self.dropped = 0

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = LogEntry(
                datetime.fromtimestamp(record.created).strftime("%H:%M:%S"),
                record.levelname, record.name, self.format(record),
            )
            with self.buffer_lock:
                if len(self.entries) == self.entries.maxlen:
                    self.dropped += 1
                self.entries.append(entry)
        except Exception:
            self.handleError(record)

    def drain(self) -> tuple[LogEntry, ...]:
        with self.buffer_lock:
            result = tuple(self.entries)
            self.entries.clear()
            if self.dropped:
                result = (LogEntry("", "WARNING", "workbench.logs", f"界面缓冲省略 {self.dropped} 条高频记录，完整记录见文件"),) + result
                self.dropped = 0
            return result


class TerminalFormatter(logging.Formatter):
    """仅对终端等级标签着色，不修改共享 LogRecord 或文件内容。"""
    COLORS = {"DEBUG": "90", "INFO": "32", "WARNING": "33", "ERROR": "31", "CRITICAL": "35"}

    def __init__(self, stream) -> None:
        super().__init__("[%(levelname)s] | %(asctime)s | %(threadName)s | %(name)s | %(message)s")
        self.colored = bool(getattr(stream, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ

    def format(self, record) -> str:
        text = super().format(record)
        color = self.COLORS.get(record.levelname)
        if self.colored and color:
            label = f"[{record.levelname}]"
            return f"\033[{color}m{label}\033[0m" + text[len(label):]
        return text


class LoggingService:
    def __init__(self, directory: Path) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / f"session-{datetime.now():%Y%m%d-%H%M%S-%f}.log"
        self.logger = logging.getLogger("workbench")
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self.buffer = _BufferHandler()
        self.file = logging.FileHandler(self.path, encoding="utf-8")
        self.terminal = logging.StreamHandler()
        formatter = logging.Formatter("[%(levelname)s] | %(asctime)s | %(threadName)s | %(name)s | %(message)s")
        self.file.setFormatter(formatter)
        self.terminal.setFormatter(TerminalFormatter(self.terminal.stream))
        self.handlers = (self.file, self.terminal, self.buffer)
        for handler in self.handlers:
            self.logger.addHandler(handler)
        self.logger.info("日志系统就绪，当前文件：%s", self.path)

    def configure(self, values: dict) -> None:
        self.logger.info("应用日志设置：等级 %s，界面容量 %d，刷新 %d ms，保留文件 %d", values["level"], values["maximum_lines"], values["flush_ms"], values["keep_files"])
        self.logger.setLevel(getattr(logging, values["level"]))
        files = sorted(self.path.parent.glob("session-*.log"), key=lambda path: path.name, reverse=True)
        for old in files[values["keep_files"]:]:
            if old != self.path and not old.is_symlink():
                try:
                    old.unlink()
                    self.logger.info("清理过期会话日志：%s", old.name)
                except OSError:
                    self.logger.warning("无法清理旧日志：%s", old.name)

    def stop(self) -> None:
        for handler in self.handlers:
            self.logger.removeHandler(handler)
            handler.close()

    def clear_all(self) -> tuple[int, tuple[str, ...]]:
        """清除会话日志；锁住当前文件句柄后截断，不中断后续写入。"""
        removed = 0
        failures = []
        for path in self.path.parent.glob("session-*.log"):
            if path == self.path or path.is_symlink() or not path.is_file():
                continue
            try:
                path.unlink()
                removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                failures.append(path.name)
        self.file.acquire()
        try:
            if self.file.stream is None or self.path.is_symlink():
                raise OSError("当前日志文件不可安全清空")
            self.file.flush()
            self.file.stream.seek(0)
            self.file.stream.truncate(0)
            self.file.flush()
            self.buffer.drain()
        except OSError:
            failures.append(self.path.name)
        finally:
            self.file.release()
        self.logger.warning("用户清除全部日志：删除旧文件 %d 个，失败 %d 个；当前会话继续记录", removed, len(failures))
        return removed, tuple(failures)
