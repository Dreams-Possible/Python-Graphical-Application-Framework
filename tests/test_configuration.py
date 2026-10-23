"""使用临时目录验证配置继承和失败保护，不触碰用户配置。"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from src.features.settings.registry import register_application
from src.features.clock.settings import SECTION as CLOCK_SETTINGS
from src.shared.configuration import Configuration, SettingsRegistry, SettingsRepository


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        registry = SettingsRegistry()
        register_application(registry)
        registry.register(CLOCK_SETTINGS)
        self.repository = SettingsRepository(Path(self.temporary.name), registry)

    def test_first_load_and_missing_fields(self):
        values = self.repository.load("app")
        path = self.repository.directory / "app.json"
        self.assertTrue(path.exists())
        path.write_text(json.dumps({"values": {"window_width": 1400}}), encoding="utf-8")
        restored = self.repository.load("app")
        self.assertEqual(restored["window_width"], 1400)
        self.assertEqual(restored["initial_page"], values["initial_page"])
        self.assertEqual(json.loads(path.read_text())["schema_version"], 1)

    def test_clock_default_migration_and_custom_server_preservation(self):
        path = self.repository.directory / "clock.json"
        for server, port, expected in (("pool.ntp.org", 123, "ntp.aliyun.com"),
                                       ("custom.example", 123, "custom.example"),
                                       ("pool.ntp.org", 124, "pool.ntp.org")):
            path.write_text(json.dumps({"schema_version": 1, "values": {"server": server, "port": port}}), encoding="utf-8")
            values = self.repository.load("clock")
            self.assertEqual(values["server"], expected)
            self.assertEqual(values["port"], port)
            self.assertEqual(json.loads(path.read_text())["schema_version"], 2)
        self.repository.save("clock", dict(values, server="pool.ntp.org", port=123))
        self.assertEqual(self.repository.load("clock")["server"], "pool.ntp.org")

    def test_appearance_is_independent_and_persistent(self):
        self.assertEqual(self.repository.load("appearance"), {"theme": "system"})
        self.repository.save("appearance", {"theme": "dark"})
        self.assertEqual(self.repository.load("appearance"), {"theme": "dark"})
        with self.assertRaises(ValueError):
            self.repository.save("appearance", {"theme": "invalid"})
        self.assertEqual(self.repository.load("appearance"), {"theme": "dark"})

    def test_failed_replace_keeps_original(self):
        values = self.repository.load("app")
        path = self.repository.directory / "app.json"
        original = path.read_bytes()
        with patch("src.shared.configuration.os.replace", side_effect=OSError("read only")):
            with self.assertRaises(OSError):
                self.repository.save("app", dict(values, window_width=1500))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(list(path.parent.glob(".app-*")), [])

    def test_restore_only_current_module_and_recreates_missing_file(self):
        configuration = Configuration(self.repository)
        configuration.update("appearance", theme="dark")
        configuration.update("app", window_width=1500, extension="custom")
        changes = []
        configuration.changed.connect(changes.append)
        configuration.restore_defaults("app")
        expected = self.repository.defaults("app")["values"]
        self.assertEqual(configuration.get("app"), expected)
        self.assertEqual(self.repository.load("app"), expected)
        self.assertEqual(configuration.get("appearance"), {"theme": "dark"})
        self.assertEqual(changes, ["app"])
        path = self.repository.directory / "app.json"
        path.unlink()
        configuration.restore_defaults("app")
        self.assertTrue(path.exists())

    def test_failed_restore_keeps_memory_and_file(self):
        configuration = Configuration(self.repository)
        configuration.update("appearance", theme="dark")
        path = self.repository.directory / "appearance.json"
        original = path.read_bytes()
        changes = []
        configuration.changed.connect(changes.append)
        with patch("src.shared.configuration.os.replace", side_effect=OSError("read only")):
            with self.assertRaises(OSError):
                configuration.restore_defaults("appearance")
        self.assertEqual(configuration.get("appearance"), {"theme": "dark"})
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(changes, [])

    def test_newer_or_corrupt_file_is_preserved(self):
        path = self.repository.directory / "app.json"
        for content in ('{"schema_version": 999, "values": {}}', "not json"):
            path.write_text(content, encoding="utf-8")
            with self.assertRaises(ValueError):
                self.repository.load("app")
            self.assertEqual(path.read_text(), content)

    def test_snapshot_is_independent_and_notification_follows_save(self):
        configuration = Configuration(self.repository)
        changes = []
        configuration.changed.connect(changes.append)
        values = configuration.get("app")
        values["window_width"] = 1500
        self.assertNotEqual(configuration.get("app")["window_width"], 1500)
        configuration.save("app", values)
        self.assertEqual(changes, ["app"])
        with patch.object(self.repository, "save", side_effect=OSError("full")):
            with self.assertRaises(OSError):
                configuration.update("app", window_width=1600)
        self.assertEqual(configuration.get("app")["window_width"], 1500)
        self.assertEqual(changes, ["app"])
