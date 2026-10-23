"""有界日志表格模型：批量插入与移除，颜色直接读取共享主题。"""

from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor


class LogTableModel(QAbstractTableModel):
    HEADERS = ("等级", "时间", "来源", "消息")
    LEVEL_COLORS = {"DEBUG": "muted", "INFO": "success", "WARNING": "warning", "ERROR": "error", "CRITICAL": "error"}

    def __init__(self, themes, limit, parent=None):
        super().__init__(parent)
        self.themes, self.limit = themes, limit
        self.entries = []
        themes.changed.connect(self.refresh_colors)

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.entries)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        entry = self.entries[index.row()]
        value = (entry.level, entry.timestamp, entry.source, entry.message)[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return value.replace("\n", " ⏎ ")
        if role == Qt.ItemDataRole.ToolTipRole:
            return value
        if role == Qt.ItemDataRole.ForegroundRole and index.column() == 0:
            return QColor(self.themes.colors[self.LEVEL_COLORS.get(entry.level, "text")])
        return None

    def replace(self, entries):
        self.beginResetModel()
        self.entries = list(entries)[-self.limit:]
        self.endResetModel()

    def append(self, entries):
        batch = list(entries)[-self.limit:]
        if not batch:
            return 0
        removed = max(0, len(self.entries) + len(batch) - self.limit)
        if removed:
            self.beginRemoveRows(QModelIndex(), 0, removed - 1)
            del self.entries[:removed]
            self.endRemoveRows()
        start = len(self.entries)
        self.beginInsertRows(QModelIndex(), start, start + len(batch) - 1)
        self.entries.extend(batch)
        self.endInsertRows()
        return removed

    def set_limit(self, limit):
        self.limit = limit
        self.replace(self.entries)

    def refresh_colors(self):
        if self.entries:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.entries) - 1, 0), [Qt.ItemDataRole.ForegroundRole])
