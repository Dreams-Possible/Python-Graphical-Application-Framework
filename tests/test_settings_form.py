"""条件行显隐后保持条纹连续，设置行容器不替代实际输入控件。"""
import unittest
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QLineEdit
from src.shared.settings_form import SettingsForm


class SettingsFormTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_hidden_rows_do_not_break_alternating_backgrounds(self):
        page = QWidget()
        form = SettingsForm(page)
        editors = [QLineEdit() for _ in range(3)]
        for i, editor in enumerate(editors):
            form.addRow(QLabel(str(i)), editor)
        self.assertEqual([row.property("alternate") for row, _, _ in form.rows], [False, True, False])
        form.setRowVisible(editors[1], False)
        self.assertFalse(form.isRowVisible(editors[1]))
        self.assertEqual([row.property("alternate") for row, _, visible in form.rows if visible], [False, True])
        form.setRowVisible(editors[1], True)
        self.assertEqual([row.property("alternate") for row, _, _ in form.rows], [False, True, False])
        page.deleteLater()
