"""俄语完整资源、系统匹配、运行时切换与历史翻译目标。"""
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from PySide6.QtWidgets import QApplication, QLabel
from src.shared.localization import Localization, load_catalog, placeholders, resolve_language
from src.shared.paths import resource_path
from src.shared.configuration import SettingsRegistry, SettingsRepository
from src.features.settings.registry import register_application
from src.features.calendar.history import HistoryRepository, HistoryService
from test_history_preload import Configuration, Tasks


class RussianTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_russian_pack_is_complete_and_preserves_template_parameters(self):
        english = load_catalog(resource_path('locales/en-US'))
        russian = load_catalog(resource_path('locales/ru-RU'))
        self.assertEqual(english.keys(), russian.keys())
        for key in english:
            self.assertEqual(placeholders(english[key]), placeholders(russian[key]), key)

    def test_system_matching_and_live_binding(self):
        texts = Localization(mode='system', system_languages=['ru-RU', 'zh-CN'])
        self.assertEqual(texts.language, 'ru-RU')
        self.assertEqual(resolve_language('system', ['ru-UA'], tuple(texts.catalogs)), 'ru-RU')
        self.assertEqual(texts.get('settings.appearance.language.ru-RU'), 'Русский')
        label = QLabel()
        texts.bind_text(label, 'common.save')
        russian = label.text()
        self.assertTrue(any('\u0400' <= char <= '\u04ff' for char in russian))
        texts.set_language('en-US')
        self.assertNotEqual(label.text(), russian)
        texts.set_language('ru-RU')
        self.assertEqual(label.text(), russian)
        label.deleteLater()

    def test_russian_selection_persists_and_history_uses_russian_target(self):
        registry = SettingsRegistry()
        register_application(registry)
        with TemporaryDirectory() as directory:
            repository = SettingsRepository(Path(directory), registry)
            repository.save('appearance', {'language': 'ru-RU', 'theme': 'light'})
            self.assertEqual(repository.load('appearance')['language'], 'ru-RU')
            texts = Localization(mode='ru-RU')
            history = HistoryService(Tasks(), Configuration(), HistoryRepository(Path(directory)), texts)
            try:
                query = history._query(date(2026, 11, 6))
                self.assertEqual(query.language, 'en')
                self.assertEqual(query.target_language, 'ru')
            finally:
                history.stop()
