from html import escape
import logging

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QCheckBox, QComboBox, QHBoxLayout, QMessageBox, QPushButton, QSizePolicy, QTextEdit, QWidget

from src.features.logs.view_model import LogsViewModel
from src.shared.widgets import choice_box, page_layout, plain_label
from src.shared.theme import ThemeManager


class LogsView(QWidget):
    def __init__(self, model: LogsViewModel, themes: ThemeManager) -> None:
        super().__init__()
        self.model = model
        self.themes = themes
        self._clear_dialog = None
        layout = page_layout(self, "日志", "查看应用事件、网络请求状态与配置变化；完整记录保存在用户日志目录。")
        files = QHBoxLayout()
        self.sessions = choice_box()
        self.sessions.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.sessions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sessions.setMinimumContentsLength(20)
        self.sessions.addItem("本次运行 · 实时日志", "")
        self.sessions.activated.connect(lambda: model.select_session(self.sessions.currentData()))
        self.refresh_files = QPushButton("刷新列表")
        self.refresh_files.clicked.connect(model.list_files)
        open_folder = QPushButton("打开日志位置")
        open_folder.clicked.connect(self._open_folder)
        self.clear_files = QPushButton("清除全部日志")
        self.clear_files.setToolTip("删除历史文件并清空当前日志；后续仍继续记录。不可撤销。")
        self.clear_files.clicked.connect(self._confirm_clear)
        files.addWidget(self.sessions, 1)
        files.addWidget(self.refresh_files)
        files.addWidget(open_folder)
        files.addWidget(self.clear_files)
        layout.addLayout(files)
        self.file_status = plain_label(f"日志目录：{model.service.path.parent}", "Muted")
        layout.addWidget(self.file_status)
        actions = QHBoxLayout()
        self.level = choice_box()
        for text, key in (("全部等级", "ALL"), ("调试", "DEBUG"), ("信息", "INFO"), ("警告", "WARNING"), ("错误", "ERROR")):
            self.level.addItem(text, key)
        self.level.activated.connect(lambda: model.set_filter(self.level.currentData()))
        self.follow = QCheckBox("跟随最新")
        self.follow.setChecked(True)
        clear = QPushButton("清空视图")
        clear.setToolTip("只清空界面缓冲，日志文件继续保留")
        clear.clicked.connect(model.clear)
        actions.addWidget(self.level)
        actions.addStretch()
        actions.addWidget(self.follow)
        actions.addWidget(clear)
        layout.addLayout(actions)
        self.console = QTextEdit()
        self.console.setObjectName("LogConsole")
        self.console.setReadOnly(True)
        self.console.setAcceptRichText(False)
        self.console.document().setMaximumBlockCount(model.configuration.get("logging")["maximum_lines"])
        self.console.setPlaceholderText("暂无日志")
        layout.addWidget(self.console, 1)
        model.appended.connect(self.append)
        model.replaced.connect(self.replace)
        model.limit_changed.connect(self.console.document().setMaximumBlockCount)
        themes.changed.connect(self._theme_changed)
        model.files_changed.connect(self._files_changed)
        model.management_changed.connect(self._management_changed)

    def _files_changed(self, names) -> None:
        self.sessions.blockSignals(True)
        self.sessions.clear()
        self.sessions.addItem("本次运行 · 实时日志", "")
        for name in names:
            self.sessions.addItem(name, name)
        if self.model.history_name and self.sessions.findData(self.model.history_name) < 0:
            self.sessions.addItem(self.model.history_name + "（文件可能已清理，当前为已载入预览）", self.model.history_name)
        self.sessions.setCurrentIndex(max(0, self.sessions.findData(self.model.history_name)))
        self.sessions.blockSignals(False)

    def _management_changed(self, message: str, busy: bool, name: str) -> None:
        self.file_status.setText(message)
        for widget in (self.sessions, self.refresh_files, self.clear_files):
            widget.setEnabled(not busy)
        self.follow.setEnabled(not name)
        if not busy:
            self.sessions.setCurrentIndex(max(0, self.sessions.findData(name)))

    def _open_folder(self) -> None:
        opened = QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.model.service.path.parent)))
        self.file_status.setText(("已请求打开日志目录：" if opened else "无法打开，请复制路径手动访问：") + str(self.model.service.path.parent))
        logging.getLogger("workbench.logs").info("打开日志目录：%s", "已交给系统" if opened else "失败")

    def _confirm_clear(self) -> None:
        if self._clear_dialog is not None:
            self._clear_dialog.raise_()
            return
        dialog = QMessageBox(self)
        dialog.setWindowTitle("清除全部日志")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText("删除本应用全部历史会话日志，并清空当前日志文件？\n\n"
                       "此操作不可撤销。当前日志文件会保留，清理完成后立即继续记录。配置及其他数据不受影响。")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Yes).setText("确认清除")
        dialog.button(QMessageBox.StandardButton.Cancel).setText("取消")
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        self._clear_dialog = dialog
        dialog.finished.connect(self._finish_clear)
        dialog.open()

    def _finish_clear(self, result: int) -> None:
        dialog, self._clear_dialog = self._clear_dialog, None
        if dialog:
            dialog.deleteLater()
        if result == QMessageBox.StandardButton.Yes:
            self.model.clear_all_files()

    def _theme_changed(self) -> None:
        previous = self.console.verticalScrollBar().value()
        self.model.refresh_view()
        if not self.follow.isChecked():
            self.console.verticalScrollBar().setValue(previous)

    def replace(self, entries: tuple) -> None:
        self.console.clear()
        self.append(entries)

    def append(self, entries: tuple) -> None:
        if not entries:
            return
        scroll = self.console.verticalScrollBar()
        previous = scroll.value()
        cursor = self.console.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        palette = self.themes.colors
        colors = {"INFO": palette["success"], "DEBUG": palette["muted"], "WARNING": palette["warning"], "ERROR": palette["error"], "CRITICAL": palette["error"]}
        for entry in entries:
            if not self.console.document().isEmpty():
                cursor.insertBlock()
            if entry.source:
                cursor.insertHtml(f'<b style="color:{colors.get(entry.level, palette["text"])}">[{escape(entry.level)}]</b> ')
            normal = QTextCharFormat()
            normal.setForeground(QColor(palette["text"]))
            cursor.setCharFormat(normal)
            cursor.insertText(f"{entry.timestamp} | {entry.source} | {entry.message}" if entry.source else entry.message)
        scroll.setValue(scroll.maximum() if self.follow.isChecked() else previous)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.model.set_active(True)
        self.model.list_files()

    def hideEvent(self, event) -> None:
        self.model.set_active(False)
        super().hideEvent(event)
