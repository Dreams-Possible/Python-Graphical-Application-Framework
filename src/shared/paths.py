"""统一只读资源与跨平台用户目录；不依赖当前工作目录。"""

from dataclasses import dataclass
from pathlib import Path
import sys

from PySide6.QtCore import QStandardPaths


def resource_path(relative: str) -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return root / "assets" / relative


@dataclass(frozen=True)
class UserPaths:
    config: Path
    data: Path
    cache: Path
    logs: Path

    @classmethod
    def discover(cls) -> "UserPaths":
        def location(kind) -> Path:
            value = QStandardPaths.writableLocation(kind)
            if not value:
                raise RuntimeError("系统没有返回可写用户目录")
            return Path(value)

        types = QStandardPaths.StandardLocation
        return cls(
            location(types.AppConfigLocation) / "modules",
            location(types.AppLocalDataLocation) / "data",
            location(types.CacheLocation),
            location(types.StateLocation) / "logs",
        )

    def ensure(self) -> None:
        for directory in (self.config, self.data, self.cache, self.logs):
            directory.mkdir(parents=True, exist_ok=True)
