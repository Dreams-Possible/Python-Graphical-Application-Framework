"""日志展示的容量边界、原文保留和终端颜色隔离。"""
import logging
import unittest
from unittest.mock import Mock, patch

from PySide6.QtCore import QObject, Signal, Qt
from src.features.logs.table_model import LogTableModel
from src.shared.logging_service import LogEntry, TerminalFormatter
from src.shared.theme import PALETTES


class Themes(QObject):
    changed = Signal()
    colors = PALETTES["light"]


class PresentationTests(unittest.TestCase):
    def test_table_capacity_multiline_and_theme(self):
        themes = Themes()
        model = LogTableModel(themes, 2)
        entries = [LogEntry("12:00", "INFO", "test", str(i)) for i in range(5)]
        model.append(entries[:2])
        self.assertEqual(model.append(entries[2:]), 2)
        self.assertEqual([e.message for e in model.entries], ["3", "4"])
        model.replace([LogEntry("", "ERROR", "", "first\nsecond")])
        index = model.index(0, 3)
        self.assertEqual(model.data(index, Qt.ItemDataRole.ToolTipRole), "first\nsecond")
        self.assertNotIn("\n", model.data(index))
        themes.colors = PALETTES["dark"]
        themes.changed.emit()
        self.assertEqual(model.data(model.index(0, 0), Qt.ItemDataRole.ForegroundRole).name(), themes.colors["error"].lower())
        model.set_limit(1)
        self.assertEqual(model.rowCount(), 1)

    def test_terminal_color_does_not_mutate_record(self):
        record = logging.LogRecord("test", logging.WARNING, "", 0, "message", (), None)
        stream = Mock()
        stream.isatty.return_value = True
        with patch.dict("os.environ", {}, clear=True):
            text = TerminalFormatter(stream).format(record)
        self.assertIn("\033[33m[WARNING]\033[0m", text)
        self.assertEqual(record.levelname, "WARNING")
        self.assertNotIn("\033", logging.Formatter("%(levelname)s %(message)s").format(record))
        stream.isatty.return_value = False
        self.assertNotIn("\033", TerminalFormatter(stream).format(record))
        stream.isatty.return_value = True
        with patch.dict("os.environ", {"NO_COLOR": "1"}):
            self.assertNotIn("\033", TerminalFormatter(stream).format(record))
