"""本地文件预览：限量读取、路径限制和弹窗异步生命周期。"""
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication
from src.features.settings.storage import StorageRepository, StorageViewModel, StorageView, PREVIEW_BYTES
from src.shared.paths import UserPaths
from src.shared.localization import Localization
from src.shared.tasks import TaskCancelled


class Tasks(QObject):
    completed = Signal(str, int, object, object, bool)

    def __init__(self):
        super().__init__()
        self.calls, self.cancelled = [], []

    def submit(self, key, function):
        self.calls.append((key, function))
        return len(self.calls)

    def cancel(self, key):
        self.cancelled.append(key)


class FilePreviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = UserPaths(*(self.root / name for name in ('config', 'data', 'cache', 'logs')))
        self.paths.ensure()
        self.repo = StorageRepository(self.paths, self.paths.logs / 'current.log')

    def tearDown(self):
        self.temp.cleanup()

    def test_json_is_pretty_printed_and_utf16_and_chinese_supported(self):
        for name, content, encoding in [('config.json', '{"name":"上海"}', 'utf-8'),
                                        ('data.txt', '测试文本', 'utf-16'), ('legacy.log', '中文日志', 'gb18030')]:
            (self.paths.config / name).write_text(content, encoding=encoding)
            preview = self.repo.preview('config', name, Event())
            self.assertIn('上海' if name.endswith('.json') else content, preview.text)
            self.assertFalse(preview.truncated)
        self.assertIn('\n', self.repo.preview('config', 'config.json', Event()).text)

    def test_large_file_is_bounded_and_partial_utf8_is_not_corrupted(self):
        (self.paths.logs / 'big.log').write_bytes(('中' * PREVIEW_BYTES).encode())
        result = self.repo.preview('logs', 'big.log', Event())
        self.assertTrue(result.truncated)
        self.assertEqual(result.text, '中' * (PREVIEW_BYTES // 3))

    def test_binary_missing_and_path_escape_report_failures(self):
        (self.paths.data / 'binary.dat').write_bytes(b'\x00\x01binary')
        for category, name, key in [('data', 'binary.dat', 'unsupported'),
                                    ('data', 'missing.txt', 'read_failed'),
                                    ('config', '../outside.txt', 'invalid_path'),
                                    ('config', str(self.root / 'outside.txt'), 'invalid_path')]:
            with self.subTest(name=name), self.assertRaises((ValueError, OSError)) as error:
                self.repo.preview(category, name, Event())
            self.assertEqual(error.exception.ui_message.key, 'storage.preview.' + key)
        stop = Event()
        stop.set()
        with self.assertRaises(TaskCancelled):
            self.repo.preview('data', 'missing.txt', stop)

    def test_double_click_opens_readonly_dialog_and_close_cancels(self):
        (self.paths.config / 'a.json').write_text('{"value":1}', encoding='utf-8')
        tasks = Tasks()
        model = StorageViewModel(self.repo, tasks)
        view = StorageView(model, Localization(mode='zh-CN'))
        view.render(self.repo.inspect('config', Event()), '', False)
        try:
            view.table.cellDoubleClicked.emit(0, 1)
            dialog = view._preview_dialog
            self.assertIsNotNone(dialog)
            self.assertTrue(dialog.content.isReadOnly())
            key, work = tasks.calls[-1]
            tasks.completed.emit(key, len(tasks.calls), work(Event()), '', False)
            self.assertIn('"value": 1', dialog.content.toPlainText())
            self.assertIn('只读', dialog.status.text())
            dialog.reject()
            self.assertIsNone(view._preview_dialog)
            self.assertIn(key, tasks.cancelled)
            tasks.completed.emit(key, len(tasks.calls), None, 'late failure', False)
            view.table.cellDoubleClicked.emit(0, 0)
            failed_dialog = view._preview_dialog
            key, _ = tasks.calls[-1]
            tasks.completed.emit(key, len(tasks.calls), None, 'file removed', False)
            self.assertEqual(failed_dialog.status.text(), 'file removed')
            self.assertEqual(failed_dialog.content.toPlainText(), '')
            failed_dialog.reject()
            # Old rows cannot preview a different category while a new scan is pending.
            model.category = 'data'
            view.table.cellDoubleClicked.emit(0, 0)
            self.assertIsNone(view._preview_dialog)
        finally:
            view.close()
            view.deleteLater()
