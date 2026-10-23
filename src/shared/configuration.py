"""注册式模块设置、默认继承、原子保存与会话状态通知。"""

from copy import deepcopy
from dataclasses import dataclass
import json
import logging
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Callable

from PySide6.QtCore import QObject, Signal

from src.shared.paths import resource_path

LOGGER = logging.getLogger("workbench.configuration")


@dataclass(frozen=True)
class SettingField:
    key: str
    label: str
    kind: str = "text"
    minimum: float = 0
    maximum: float = 100000
    choices: tuple[tuple[str, str], ...] = ()
    hint: str = ""


@dataclass(frozen=True)
class SettingsSection:
    key: str
    title: str
    description: str
    fields: tuple[SettingField, ...]
    migrate: Callable[[int, dict], dict] | None = None


class SettingsRegistry:
    def __init__(self) -> None:
        self._sections: dict[str, SettingsSection] = {}

    def register(self, section: SettingsSection) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", section.key) or section.key in self._sections:
            raise ValueError("设置模块 ID 非法或重复")
        self._sections[section.key] = section
        LOGGER.debug("设置模块已注册：%s，字段数 %d", section.key, len(section.fields))

    @property
    def sections(self) -> tuple[SettingsSection, ...]:
        return tuple(self._sections.values())

    def section(self, key: str) -> SettingsSection:
        return self._sections[key]


def merge_defaults(default: dict, current: dict) -> dict:
    """补齐缺失字段，同时保留已有值及未知扩展字段。"""
    result = deepcopy(current)
    for key, value in default.items():
        if key not in result:
            result[key] = deepcopy(value)
        elif isinstance(value, dict):
            if not isinstance(result[key], dict):
                raise ValueError(f"配置字段 {key} 应为对象")
            result[key] = merge_defaults(value, result[key])
    return result


class SettingsRepository:
    def __init__(self, directory: Path, registry: SettingsRegistry, defaults: Path | None = None) -> None:
        self.directory = directory
        self.registry = registry
        self.defaults_directory = defaults or resource_path("defaults")

    def defaults(self, key: str) -> dict:
        self.registry.section(key)
        return json.loads((self.defaults_directory / f"{key}.json").read_text(encoding="utf-8"))

    def validate(self, key: str, values: dict) -> None:
        if not isinstance(values, dict):
            raise ValueError("模块配置值必须是对象")
        for field in self.registry.section(key).fields:
            value = values.get(field.key)
            if field.kind == "bool":
                valid = type(value) is bool
            elif field.kind in ("int", "float"):
                valid = type(value) in ((int,) if field.kind == "int" else (int, float))
                valid = valid and math.isfinite(value) and field.minimum <= value <= field.maximum
            else:
                valid = isinstance(value, str) and bool(value.strip()) and len(value) <= 2048
                if field.kind == "choice":
                    valid = valid and value in dict(field.choices)
            if not valid:
                raise ValueError(f"{field.label}：值无效或不在允许范围内")

    def load(self, key: str) -> dict:
        default = self.defaults(key)
        path = self.directory / f"{key}.json"
        LOGGER.info("读取模块配置：%s，文件 %s", key, path)
        try:
            document = json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
            if not isinstance(document, dict) or type(document.get("schema_version", default["schema_version"])) is not int:
                raise ValueError("schema_version 无效")
            if document.get("schema_version", default["schema_version"]) > default["schema_version"]:
                raise ValueError("配置由更高版本创建，请升级应用")
            migrated = deepcopy(document)
            previous_version = document.get("schema_version", 0)
            migration = self.registry.section(key).migrate
            if previous_version < default["schema_version"] and migration:
                LOGGER.info("执行配置迁移：%s，版本 %d → %d", key, previous_version, default["schema_version"])
                migrated["values"] = migration(previous_version, deepcopy(document.get("values", {})))
            merged = merge_defaults(default, migrated)
            merged["schema_version"] = default["schema_version"]
            self.validate(key, merged["values"])
            if not path.exists() or merged != document:
                LOGGER.info("配置需要写回：%s，原因 %s", key, "首次创建" if not path.exists() else "迁移或缺项补齐")
                self._write(key, merged)
                LOGGER.info("配置初始化或补齐：%s", key)
            LOGGER.info("配置加载完成：%s，版本 %d", key, merged["schema_version"])
            return deepcopy(merged["values"])
        except (OSError, ValueError, TypeError) as error:
            LOGGER.exception("配置加载失败，未静默重置：%s", key)
            raise ValueError(f"无法加载 {key}.json：{error}") from error

    def save(self, key: str, values: dict) -> None:
        self.validate(key, values)
        document = {"schema_version": self.defaults(key)["schema_version"], "values": values}
        self._write(key, document)

    def _write(self, key: str, document: dict) -> None:
        LOGGER.debug("开始原子写入配置：%s", key)
        self.directory.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix=f".{key}-", dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(document, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.directory / f"{key}.json")
            LOGGER.debug("配置原子替换完成：%s", key)
        except OSError:
            LOGGER.exception("配置写入失败：%s", key)
            raise
        finally:
            temporary.unlink(missing_ok=True)


class Configuration(QObject):
    changed = Signal(str)

    def __init__(self, repository: SettingsRepository) -> None:
        super().__init__()
        self.repository = repository
        self._values = {section.key: repository.load(section.key) for section in repository.registry.sections}

    def get(self, key: str) -> dict[str, Any]:
        return deepcopy(self._values[key])

    def save(self, key: str, values: dict) -> None:
        if self._values[key] == values:
            LOGGER.debug("配置内容未改变，跳过保存：%s", key)
            return
        fields = sorted(field for field in self._values[key].keys() | values.keys()
                        if self._values[key].get(field) != values.get(field))
        LOGGER.info("请求保存配置：%s，变更字段 %s", key, ", ".join(fields))
        self.repository.save(key, values)
        self._values[key] = deepcopy(values)
        LOGGER.info("模块配置已保存：%s", key)
        self.changed.emit(key)
        LOGGER.debug("配置变化通知已发出：%s", key)

    def update(self, key: str, **changes: Any) -> None:
        values = self.get(key)
        values.update(changes)
        self.save(key, values)

    def restore_defaults(self, key: str) -> None:
        """显式重置单个模块；即使内存已是默认值也重新落盘。"""
        values = self.repository.defaults(key)["values"]
        self.repository.save(key, values)
        self._values[key] = deepcopy(values)
        LOGGER.info("模块配置已恢复默认：%s", key)
        self.changed.emit(key)
