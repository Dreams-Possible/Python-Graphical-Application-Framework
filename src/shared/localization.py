"""应用展示资源：语言、模板和 Qt 本地格式；不持有业务状态。"""
from src.shared.messages import Message, message
import json
import logging
import weakref
from pathlib import Path
from string import Formatter

from PySide6.QtCore import QCoreApplication, QEvent, QLibraryInfo, QObject, QLocale, QSignalBlocker, QTranslator, Signal, Slot

from src.shared.paths import resource_path

LOGGER = logging.getLogger("workbench.localization")




def placeholders(template: str) -> set[str]:
    fields = set()
    for _, name, _, _ in Formatter().parse(template):
        if name is not None:
            if not name.isidentifier():
                raise ValueError(f"Invalid named placeholder: {name}")
            fields.add(name)
    return fields


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate resource key: {key}")
        result[key] = value
    return result


def load_catalog(directory: Path) -> dict[str, str]:
    result = {}
    files = sorted(directory.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"No language resources: {directory}")
    for path in files:
        entries = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(entries, dict):
            raise ValueError(f"Invalid language catalog: {path}")
        for key, value in entries.items():
            if key in result or not isinstance(value, str):
                raise ValueError(f"Invalid or duplicate resource: {key}")
            placeholders(value)
            result[key] = value
    return result


def resolve_language(mode: str, system_languages: list[str]) -> str:
    if mode in ("zh-CN", "en-US"):
        return mode
    if mode != "system":
        raise ValueError(f"Unsupported software language: {mode}")
    if system_languages and system_languages[0].replace("_", "-").lower().split("-")[0] == "zh":
        return "zh-CN"
    return "en-US"


class Localization(QObject):
    changed = Signal()

    def __init__(self, directory=None, mode="system", system_languages=None):
        super().__init__()
        self.directory = Path(directory) if directory else resource_path("locales")
        self.catalogs = {"zh-CN": load_catalog(self.directory / "zh-CN")}
        try:
            self.catalogs["en-US"] = load_catalog(self.directory / "en-US")
        except FileNotFoundError:
            LOGGER.warning("English catalog missing; using the default catalog")
            self.catalogs["en-US"] = {}
        for key in self.catalogs["zh-CN"].keys() & self.catalogs["en-US"].keys():
            if placeholders(self.catalogs["zh-CN"][key]) != placeholders(self.catalogs["en-US"][key]):
                raise ValueError(f"Translation parameters differ: {key}")
        self.system_languages = system_languages
        self.language = ""
        self._missing = set()
        self.configuration = None
        self._application = None
        self._qt_translator = None
        self._windows = weakref.WeakSet()
        self.set_language(mode)

    def bind(self, configuration):
        self.configuration = configuration
        configuration.changed.connect(self._configured)
        self._configured("appearance")

    def _configured(self, module):
        if module == "appearance":
            self.set_language(self.configuration.get("appearance")["language"])

    def set_language(self, mode):
        language = resolve_language(mode, self.system_languages if self.system_languages is not None else QLocale.system().uiLanguages())
        self.mode = mode
        if language == self.language:
            return
        drafts, blockers = self._capture_number_edits()
        try:
            self.language = language
            self.locale = QLocale(language.replace("-", "_"))
            self._install_qt_translation()
            self.changed.emit()
        finally:
            self._restore_number_edits(drafts)
            blockers.clear()

    def bind_window(self, window):
        self._windows.add(window)
        self._application = QCoreApplication.instance()
        self._application.installEventFilter(self)
        self._install_qt_translation()
        return _WindowLocaleBinding(self, window)

    def _capture_number_edits(self):
        from PySide6.QtWidgets import QDoubleSpinBox, QSpinBox
        from shiboken6 import isValid
        drafts, blockers = [], []
        for window in self._windows:
            if not isValid(window):
                continue
            for editor in window.findChildren(QObject):
                if not isinstance(editor, (QSpinBox, QDoubleSpinBox)):
                    continue
                line = editor.lineEdit()
                # 区域与单位变化不能触发用户编辑信号；有效数值由 Qt 正常重排。
                blockers.extend((QSignalBlocker(editor), QSignalBlocker(line)))
                if line.isModified() or not editor.hasAcceptableInput():
                    prefix, suffix, value = editor.prefix(), editor.suffix(), line.text()
                    if prefix and value.startswith(prefix):
                        value = value[len(prefix):]
                    if suffix and value.endswith(suffix):
                        value = value[:-len(suffix)]
                    drafts.append((editor, value, line.cursorPosition() - len(prefix),
                                   line.selectionStart() - len(prefix) if line.hasSelectedText() else -1,
                                   len(line.selectedText()), line.isModified()))
        return drafts, blockers

    @staticmethod
    def _restore_number_edits(drafts):
        from shiboken6 import isValid
        for editor, value, cursor, start, length, modified in drafts:
            if not isValid(editor):
                continue
            line = editor.lineEdit()
            line.setText(editor.prefix() + value + editor.suffix())
            if start >= 0:
                line.setSelection(start + len(editor.prefix()), length)
            else:
                line.setCursorPosition(max(0, cursor + len(editor.prefix())))
            line.setModified(modified)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.LocaleChange and self.mode == "system":
            self.set_language("system")
        return super().eventFilter(watched, event)

    def _install_qt_translation(self):
        if self._application is None:
            return
        self.release_qt_translation()
        translator = QTranslator(self)
        directory = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
        if translator.load(self.locale, "qtbase", "_", directory):
            self._application.installTranslator(translator)
            self._qt_translator = translator
        else:
            translator.deleteLater()

    def release_qt_translation(self):
        if self._application is not None and self._qt_translator is not None:
            self._application.removeTranslator(self._qt_translator)
            self._qt_translator.deleteLater()
            self._qt_translator = None

    def get(self, key: str, **parameters) -> str:
        if key + ".other" in self.catalogs["zh-CN"]:
            key += ".one" if self.language == "en-US" and parameters.get("count") == 1 else ".other"
        template = self.catalogs[self.language].get(key)
        if template is None:
            if (self.language, key) not in self._missing:
                LOGGER.warning("Missing translation: %s / %s", self.language, key)
                self._missing.add((self.language, key))
            template = self.catalogs["zh-CN"].get(key, f"[{key}]")
        expected = placeholders(template)
        if expected != parameters.keys():
            raise ValueError(f"Parameters for {key}: expected {sorted(expected)}, got {sorted(parameters)}")
        values = {name: self.render(value) if isinstance(value, Message) else value for name, value in parameters.items()}
        return template.format_map(values)

    def render(self, value) -> str:
        """原始字符串仅用于用户／外部数据和原始诊断内容。"""
        return self.get(value.key, **dict(value.parameters)) if isinstance(value, Message) else str(value)

    def number(self, value, decimals=None):
        if value is None:
            return self.get("common.unavailable")
        if isinstance(value, int):
            return self.locale.toString(value)
        return self.locale.toString(float(value), "g", 6) if decimals is None else self.locale.toString(float(value), "f", decimals)

    def date(self, value, long=False):
        from PySide6.QtCore import QDate
        day = value if isinstance(value, QDate) else QDate(value.year, value.month, value.day)
        return self.locale.toString(day, QLocale.FormatType.LongFormat if long else QLocale.FormatType.ShortFormat)

    def short_date(self, value):
        from PySide6.QtCore import QDate
        day = value if isinstance(value, QDate) else QDate(value.year, value.month, value.day)
        return self.locale.toString(day, self.get("common.format.short_date"))

    def time(self, value, seconds=True):
        from PySide6.QtCore import QTime
        clock = QTime(value.hour, value.minute, value.second)
        return self.locale.toString(clock, self.get("common.format.time" if seconds else "common.format.time_minutes"))

    def weekday(self, day, short=False):
        return self.locale.dayName(day, QLocale.FormatType.ShortFormat if short else QLocale.FormatType.LongFormat)

    def bind_text(self, target, key, setter="setText", **parameters):
        """绑定对象拥有订阅生命周期，销毁控件后 Qt 自动断开连接。"""
        return self.set_text(target, message(key, **parameters), setter)

    def set_text(self, target, value, setter="setText"):
        bindings = getattr(target, "_text_bindings", None)
        if bindings is None:
            bindings = {}
            target._text_bindings = bindings
        binding = bindings.get(setter)
        if binding is None:
            binding = _TextBinding(self, target, value, setter)
            bindings[setter] = binding
        else:
            binding.value = value
            binding.refresh()
        return binding


class _TextBinding(QObject):
    def __init__(self, texts, target, value, setter):
        super().__init__(target)
        self.texts, self.target, self.value, self.setter = texts, target, value, setter
        texts.changed.connect(self.refresh)
        self.refresh()

    @Slot()
    def refresh(self):
        value = self.value
        if isinstance(value, Message):
            parameters = {name: parameter() if callable(parameter) else parameter for name, parameter in value.parameters}
            value = self.texts.get(value.key, **parameters)
        getattr(self.target, self.setter)(str(value))


class _WindowLocaleBinding(QObject):
    def __init__(self, texts, window):
        super().__init__(window)
        self.texts, self.window = texts, window
        texts.changed.connect(self.refresh)
        self.refresh()

    @Slot()
    def refresh(self):
        self.window.setLocale(self.texts.locale)
