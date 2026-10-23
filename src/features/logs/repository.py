"""只访问本应用会话日志；历史读取限量，避免大文件阻塞界面。"""

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import re
from threading import Event

from src.shared.logging_service import LogEntry, LoggingService
from src.shared.tasks import check_cancelled

HEADER = re.compile(r"^\[(\w+)\] \| ([^|]+) \| (?:(\S+) \| )?(workbench(?:\.[^\s|]+)?) \| (.*)$")


@dataclass(frozen=True)
class HistorySnapshot:
    name: str
    entries: tuple[LogEntry, ...]
    limited: bool


class LogRepository:
    def __init__(self, service: LoggingService) -> None:
        self.service = service
        self.directory = service.path.parent

    def files(self, stop: Event) -> tuple[str, ...]:
        names = []
        for path in self.directory.glob("session-*.log"):
            check_cancelled(stop)
            if path != self.service.path and path.is_file() and not path.is_symlink():
                names.append(path.name)
        return tuple(sorted(names, reverse=True))

    def read(self, name: str, limit: int, stop: Event) -> HistorySnapshot:
        if Path(name).name != name or not name.startswith("session-") or not name.endswith(".log"):
            raise ValueError("无效日志文件名")
        path = self.directory / name
        if path.is_symlink() or path.resolve().parent != self.directory.resolve():
            raise ValueError("不允许读取日志目录之外的文件")
        check_cancelled(stop)
        maximum = 2 * 1024 * 1024
        with path.open("rb") as stream:
            stream.seek(0, 2)
            size = stream.tell()
            start = max(0, size - maximum)
            stream.seek(start)
            raw = stream.read(maximum)
        if start:
            raw = raw.partition(b"\n")[2]  # 不展示截断的半行。
        entries = deque(maxlen=limit)
        level = "RAW"
        count = 0
        for line in raw.decode("utf-8", errors="replace").splitlines():
            check_cancelled(stop)
            count += 1
            match = HEADER.match(line)
            if match:
                level, stamp, thread, source, message = match.groups()
                entries.append(LogEntry(stamp.strip(), level, source,
                                        f"{thread} | {message}" if thread else message))
            else:
                entries.append(LogEntry("", level, "", line))
        return HistorySnapshot(name, tuple(entries), bool(start) or count > limit)

    def clear_all(self, stop: Event) -> tuple[int, tuple[str, ...]]:
        check_cancelled(stop)
        return self.service.clear_all()
