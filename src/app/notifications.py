"""异步错误共用一个非模态窗口，避免嵌套事件循环。"""

from collections import deque
import logging
from PySide6.QtCore import QObject, Qt, Slot
from PySide6.QtWidgets import QMessageBox, QWidget

LOGGER = logging.getLogger("workbench.notifications")


class NotificationCenter(QObject):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._window = parent
        self._dialog = None
        self._messages = deque(maxlen=20)

    @Slot(str)
    def report(self, message: str) -> None:
        if message not in self._messages:
            self._messages.append(message)
        LOGGER.info("异步通知已汇总，当前 %d 条", len(self._messages))
        if self._dialog is None:
            dialog = QMessageBox(self._window)
            dialog.setWindowTitle("应用提示")
            dialog.setIcon(QMessageBox.Icon.Warning)
            dialog.setTextFormat(Qt.TextFormat.PlainText)
            dialog.setStandardButtons(QMessageBox.StandardButton.Ok)
            dialog.setWindowModality(Qt.WindowModality.NonModal)
            dialog.finished.connect(self._closed)
            self._dialog = dialog
        self._dialog.setText("\n\n".join(self._messages))
        self._dialog.show()

    def _closed(self, _result: int) -> None:
        LOGGER.info("异步通知窗口已关闭")
        dialog, self._dialog = self._dialog, None
        self._messages.clear()
        if dialog:
            dialog.deleteLater()

    def close(self) -> None:
        if self._dialog:
            self._dialog.close()
