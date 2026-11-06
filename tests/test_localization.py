"""语言资源验证、默认继承、绑定生命周期与无副作用的运行时切换。"""
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

from PySide6.QtGui import QKeySequence
from PySide6.QtCore import QCoreApplication, QDate, QEvent, Qt
from PySide6.QtWidgets import QApplication, QLabel, QLineEdit, QPushButton, QSpinBox, QWidget
from src.shared.localization import Localization, load_catalog, placeholders, resolve_language
from src.shared.messages import message
from src.shared.errors import ui_error, error_message
from src.shared.paths import resource_path, UserPaths
from src.shared.logging_service import LoggingService, LogEntry
from src.shared.theme import ThemeManager
from src.app.bootstrap import create_main_window
from src.features.weather.providers import parse_report
from src.features.weather.models import WeatherState


class LocalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_owned_view_text_does_not_embed_chinese_literals(self):
        import ast
        root = Path(__file__).resolve().parents[1]
        files = list((root / "src" / "app").glob("*.py"))
        files += [path for path in (root / "src" / "features").rglob("*.py")
                  if path.stem in ("view", "timer_view", "stopwatch_view", "forecast_view", "picker", "table_model")]
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str) or not any("\u4e00" <= c <= "\u9fff" for c in node.value):
                    continue
                parent = parents.get(node)
                if isinstance(parent, ast.Expr):
                    continue  # Module, class and method documentation.
                chain = []
                current = node
                while current in parents:
                    current = parents[current]
                    chain.append(current)
                if any(isinstance(ancestor, ast.Call) and isinstance(ancestor.func, ast.Attribute)
                       and ancestor.func.attr in ("debug", "info", "warning", "error", "exception") for ancestor in chain):
                    continue  # Original diagnostic log records are intentionally preserved.
                self.fail(f"Hardcoded display text at {path.relative_to(root)}:{node.lineno}: {node.value}")

    def test_catalog_keys_parameters_and_plural_forms(self):
        texts = Localization(mode="en-US")
        chinese, english = texts.catalogs["zh-CN"], texts.catalogs["en-US"]
        self.assertEqual(chinese.keys(), english.keys())
        for key in chinese:
            self.assertEqual(placeholders(chinese[key]), placeholders(english[key]), key)
        self.assertIn("1 location.", texts.get("weather.search.results", count=1))
        self.assertIn("2 locations.", texts.get("weather.search.results", count=2))
        with self.assertRaises(ValueError):
            texts.get("weather.search.results")

    def test_system_language_and_manual_override(self):
        self.assertEqual(resolve_language("system", ["zh-TW", "en-US"]), "zh-CN")
        self.assertEqual(resolve_language("system", ["en-GB"]), "en-US")
        self.assertEqual(resolve_language("system", ["fr-FR"]), "en-US")
        self.assertEqual(resolve_language("system", ["fr-FR", "zh-CN"]), "en-US")
        self.assertEqual(resolve_language("en-US", ["zh-CN"]), "en-US")
        with self.assertRaises(ValueError):
            resolve_language("bad", [])

    def test_missing_translation_fallback_and_duplicates(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for language in ("zh-CN", "en-US"):
                (root / language).mkdir()
            (root / "zh-CN" / "common.json").write_text('{}', encoding="utf-8")
            (root / "en-US" / "common.json").write_text('{"greeting": "Hello {name}"}', encoding="utf-8")
            texts = Localization(root, "zh-CN")
            self.assertEqual(texts.get("greeting", name="Sam"), "Hello Sam")
            self.assertEqual(texts.get("missing"), "[missing]")
            (root / "en-US" / "common.json").write_text('{"x": "one", "x": "two"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                load_catalog(root / "en-US")
            (root / "zh-CN" / "common.json").write_text('{"greeting": "你好 {other}"}', encoding="utf-8")
            (root / "en-US" / "common.json").write_text('{"greeting": "Hello {name}"}', encoding="utf-8")
            with self.assertRaises(ValueError):
                Localization(root)

    def test_resource_path_in_frozen_layout(self):
        with TemporaryDirectory() as directory:
            shutil.copytree(resource_path("locales"), Path(directory) / "assets" / "locales")
            with patch.object(sys, "_MEIPASS", directory, create=True):
                self.assertEqual(Localization(mode="en-US").get("common.save"), "Save settings")

    def test_binding_and_structured_error(self):
        texts = Localization(mode="zh-CN")
        label = QLabel()
        texts.bind_text(label, "common.save")
        texts.set_language("en-US")
        self.assertEqual(label.text(), "Save settings")
        error = ui_error(ValueError, "errors.settings_invalid", field=message("settings.app.window_width.label"))
        self.assertIn("Window width", texts.render(error_message(error)))
        label.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        texts.set_language("zh-CN")  # Deleted widgets must not leave callbacks behind.

    def test_entire_window_language_change_preserves_state_and_does_not_submit_tasks(self):
        texts = Localization(system_languages=["zh-CN"])
        themes = ThemeManager(self.app)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = UserPaths(*(root / name for name in ("config", "data", "cache", "logs")))
            paths.ensure()
            logs = LoggingService(paths.logs)
            logs.logger.removeHandler(logs.terminal)
            window = None
            try:
                with patch("src.app.bootstrap.QTimer.singleShot"), patch("src.shared.tasks.TaskRunner.submit", return_value=1) as submit:
                    window = create_main_window(paths, logs, themes, texts)
                    settings = window._pages.widget(4)
                    self.assertEqual(settings.configuration.get("appearance")["language"], "system")
                    app_index = next(i for i, section in enumerate(settings.registry.sections) if section.key == "app")
                    settings.categories.setCurrentRow(app_index)
                    editor = settings._editors["window_width"]
                    editor.setValue(1234)
                    clock = window._pages.widget(0)
                    clock.timer_view.model.start(600)
                    deadline = clock.timer_view.model.deadline
                    clock.stopwatch_view.model.start()
                    started_at = clock.stopwatch_view.model._started_at
                    weather = window._pages.widget(1)
                    weather.query.setText("user query")
                    calendar = window._pages.widget(2)
                    calendar.date = calendar.shown = QDate(2026, 11, 13)
                    calendar.set_mode("day")
                    log_view = window._pages.widget(3)
                    entry = LogEntry("12:00", "INFO", "external", "原始日志不翻译")
                    log_view.model.set_filter("INFO")
                    log_view.replace((entry,))
                    log_view.level.setCurrentIndex(2)
                    window._about()
                    settings._reset()  # Keep a confirmation dialog open while switching.
                    submit.reset_mock()
                    texts.set_language("en-US")
                    self.app.processEvents()
                    submit.assert_not_called()
                    self.assertIs(settings._editors["window_width"], editor)
                    self.assertEqual(editor.value(), 1234)
                    self.assertEqual(clock.timer_view.model.deadline, deadline)
                    self.assertEqual(clock.stopwatch_view.model._started_at, started_at)
                    self.assertEqual(weather.query.text(), "user query")
                    self.assertEqual(calendar.date, QDate(2026, 11, 13))
                    self.assertEqual(calendar.mode, "day")
                    self.assertEqual(log_view.table_model.entries, [entry])
                    self.assertEqual(log_view.level.currentData(), "INFO")
                    self.assertEqual(log_view.model._level, "INFO")
                    self.assertEqual(window._navigation_items[0].text(), "Clock")
                    quit_action = window._menus[0].actions()[0]
                    self.assertEqual(quit_action.text(), "Quit")
                    self.assertEqual(quit_action.shortcut().toString(QKeySequence.SequenceFormat.PortableText), "Ctrl+Q")
                    self.assertEqual(settings._reset_dialog.windowTitle(), "Restore default settings")
                    self.assertEqual(settings._reset_dialog.button(settings._reset_dialog.StandardButton.Cancel).text(), "Cancel")
                    self.assertIn("Restore", settings._reset_dialog.text())
                    # Every registered form must resolve its labels and option keys.
                    for i in range(len(settings.registry.sections)):
                        settings.categories.setCurrentRow(i)
                        texts.set_language("zh-CN")
                        texts.set_language("en-US")
                    self.assertEqual(texts._missing, set())
                    calendar_section = settings.registry.section("calendar")
                    self.assertNotIn("history_language", [field.key for field in calendar_section.fields])
                    section_keys = [section.key for section in settings.registry.sections]
                    settings.categories.setCurrentRow(section_keys.index("weather"))
                    for key in ("follow_current_location", "location_name", "latitude", "longitude"):
                        self.assertNotIn(key, settings._editors)
                    translation_index = section_keys.index("translation")
                    self.assertEqual(section_keys[translation_index + 1], "location")
                    settings.categories.setCurrentRow(translation_index)
                    provider = settings._editors["provider"]
                    concurrency = settings._editors["max_workers"]
                    self.assertEqual((concurrency.minimum(), concurrency.maximum(), concurrency.value()), (1, 10, 10))
                    concurrency.setValue(3)
                    for value in ("mymemory", "google", "baidu", "youdao", "libre"):
                        provider.setCurrentIndex(provider.findData(value))
                        for key, control in settings._editors.items():
                            if key not in ("provider", "timeout_seconds", "max_workers"):
                                self.assertEqual(settings._translation_form.isRowVisible(control), key.startswith(value + "_"))
                    provider.setCurrentIndex(provider.findData("google"))
                    self.assertEqual(settings._editors["google_key"].echoMode(), QLineEdit.EchoMode.Password)
                    settings._save()  # Missing credentials must not persist the provider.
                    self.assertEqual(settings.configuration.get("translation")["provider"], "mymemory")
                    settings._editors["google_key"].setText("test-key")
                    settings._save()
                    self.assertEqual(settings.configuration.get("translation")["provider"], "google")
                    self.assertEqual(settings.configuration.get("translation")["max_workers"], 3)
                    settings.categories.setCurrentRow(0)
                    settings._editors["language"].setCurrentIndex(settings._editors["language"].findData("en-US"))
                    settings._save()
                    self.assertEqual(settings.configuration.get("appearance")["language"], "en-US")
                    saved = json.loads((paths.config / "appearance.json").read_text(encoding="utf-8"))
                    self.assertEqual(saved["values"]["language"], "en-US")
            finally:
                if window:
                    window.close()
                    window.deleteLater()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                texts.release_qt_translation()
                logs.stop()

    def test_incomplete_number_edit_survives_locale_and_suffix_change(self):
        texts = Localization(mode="zh-CN")
        window = QWidget()
        editor = QSpinBox(window)
        editor.setRange(960, 3840)
        editor.setValue(1234)
        texts.bind_text(editor, "clock.timer.seconds", setter="setSuffix")
        texts.bind_window(window)
        editor.lineEdit().setText("1" + editor.suffix())
        editor.lineEdit().setCursorPosition(1)
        self.assertFalse(editor.hasAcceptableInput())
        texts.set_language("en-US")
        self.assertEqual(editor.lineEdit().text(), "1 s")
        self.assertEqual(editor.lineEdit().cursorPosition(), 1)
        self.assertEqual(editor.value(), 1234)
        texts.release_qt_translation()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)

    def test_legacy_settings_gain_system_language_without_changing_theme(self):
        from src.shared.configuration import SettingsRegistry, SettingsRepository
        from src.features.settings.registry import register_application
        with TemporaryDirectory() as directory:
            path = Path(directory) / "appearance.json"
            path.write_text(json.dumps({"schema_version": 1, "values": {"theme": "dark"}}), encoding="utf-8")
            registry = SettingsRegistry()
            register_application(registry)
            values = SettingsRepository(Path(directory), registry).load("appearance")
            self.assertEqual(values, {"theme": "dark", "language": "system"})

    def test_file_category_permissions_use_identifiers_not_labels(self):
        from threading import Event
        from src.features.settings.storage import StorageRepository
        with TemporaryDirectory() as directory:
            root = Path(directory)
            paths = UserPaths(*(root / name for name in ("config", "data", "cache", "logs")))
            paths.ensure()
            protected = paths.config / "keep.json"
            protected.write_text("{}")
            cached = paths.cache / "temporary.txt"
            cached.write_text("cache")
            repository = StorageRepository(paths, paths.logs / "session-current.log")
            self.assertEqual(set(repository.directories), {"config", "data", "cache", "logs"})
            for language in ("zh-CN", "en-US"):
                texts = Localization(mode=language)
                self.assertTrue(texts.get("storage.category.config"))
                with self.assertRaises(ValueError):
                    repository.clear("config", Event())
                self.assertTrue(protected.exists())
            repository.clear("cache", Event())
            self.assertFalse(cached.exists())

    def test_worker_preserves_localizable_error_payload(self):
        from threading import Event
        from src.shared.tasks import _Worker
        outcomes = []
        def fail(stop):
            raise ui_error(ValueError, "errors.weather_response")
        worker = _Worker("test", 1, fail, Event())
        worker.outcome.connect(lambda key, generation, result, error, cancelled: outcomes.append(error))
        worker.run()
        self.assertEqual(outcomes[0].key, "errors.weather_response")
        self.assertIn("Weather response", Localization(mode="en-US").render(outcomes[0]))

    def test_weather_translation_keeps_plot_values_and_expansion(self):
        from src.features.weather.view import WeatherDetails
        texts = Localization(mode="zh-CN")
        view = WeatherDetails(texts)
        now = 1793836800
        report = parse_report({"utc_offset_seconds": 0, "timezone": "UTC",
            "current": {"time": now, "temperature_2m": 12.5, "weather_code": 61},
            "hourly": {"time": [now, now + 3600], "temperature_2m": [12.5, 13.2], "weather_code": [61, 0]},
            "daily": {"time": [now], "temperature_2m_min": [10], "temperature_2m_max": [16]}}, {"location_name": "External city"})
        view.render(WeatherState(report=report))
        view.hours._toggle_details(1)
        texts.set_language("en-US")
        self.assertEqual(view.hours.selected_index, 1)
        self.assertEqual(view.hours.rows[0].temperature, 12.5)
        self.assertEqual(view.symbol.condition, 61)
        self.assertIn("Light rain", view.summary.text())
        view.close()
