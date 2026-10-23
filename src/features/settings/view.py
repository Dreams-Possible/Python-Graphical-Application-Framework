"""从设置注册信息生成表单；保存时只合并用户实际修改的字段。"""

import logging

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from src.features.settings.storage import StorageView, StorageViewModel
from src.shared.configuration import Configuration, SettingsRegistry
from src.shared.widgets import NavigationDelegate, choice_box, page_layout, plain_label

LOGGER = logging.getLogger("workbench.settings")


class SettingsView(QWidget):
    def __init__(self, registry: SettingsRegistry, configuration: Configuration, storage: StorageViewModel) -> None:
        super().__init__()
        self.registry, self.configuration = registry, configuration
        self._key = ""
        self._editors = {}
        self._baseline = {}
        self._reset_dialog = None
        layout = page_layout(self, "设置", "调整外观与功能偏好，保存后自动记住你的选择。")
        body = QHBoxLayout()
        self.categories = QListWidget()
        self.categories.setObjectName("SettingsCategories")
        self.categories.setFixedWidth(168)
        self.categories.setItemDelegate(NavigationDelegate(self.categories))
        self.categories.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.categories.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.categories.addItems([section.title for section in registry.sections] + ["本地文件"])
        self.pages = QStackedWidget()
        form_page = QWidget()
        form_layout = QVBoxLayout(form_page)
        form_layout.setContentsMargins(12, 0, 0, 0)
        self.description = plain_label(name="Muted")
        form_layout.addWidget(self.description)
        self.open_configuration = QPushButton("打开配置位置")
        self.open_configuration.clicked.connect(self._open_configuration)
        form_layout.addWidget(self.open_configuration, 0, Qt.AlignmentFlag.AlignLeft)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        form_layout.addWidget(self.scroll, 1)
        self.feedback = plain_label(name="Muted")
        form_layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        reset = QPushButton("恢复当前分类默认配置")
        reset.clicked.connect(self._reset)
        save = QPushButton("保存设置")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        actions.addWidget(reset)
        actions.addStretch()
        actions.addWidget(save)
        form_layout.addLayout(actions)
        self.storage = StorageView(storage)
        self.pages.addWidget(form_page)
        self.pages.addWidget(self.storage)
        body.addWidget(self.categories)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        self.categories.currentRowChanged.connect(self._select)
        self.categories.setCurrentRow(0)

    def _select(self, index: int) -> None:
        if index == len(self.registry.sections):
            self.pages.setCurrentIndex(1)
            self.storage.model.refresh()
            return
        if index < 0:
            return
        self.pages.setCurrentIndex(0)
        section = self.registry.sections[index]
        self._key = section.key
        LOGGER.debug("打开设置分类：%s", section.key)
        path = self.configuration.repository.directory / f"{section.key}.json"
        self.description.setText(section.description + f"\n配置文件：{path}")
        self.open_configuration.setToolTip(f"打开 {path.name} 所在文件夹")
        self._baseline = self.configuration.get(section.key)
        self._editors = {}
        content = QWidget()
        form = QFormLayout(content)
        form.setContentsMargins(16, 20, 16, 20)
        form.setSpacing(16)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        for field in section.fields:
            if field.kind == "bool":
                editor = QCheckBox("启用")
            elif field.kind in ("int", "float"):
                editor = QSpinBox() if field.kind == "int" else QDoubleSpinBox()
                if field.kind == "float":
                    editor.setDecimals(5)
                editor.setRange(field.minimum, field.maximum)
            elif field.kind == "choice":
                editor = choice_box()
                for value, label in field.choices:
                    editor.addItem(label, value)
            else:
                editor = QLineEdit()
            editor.setToolTip(field.hint)
            editor.setAccessibleName(field.label)
            self._editors[field.key] = editor
            form.addRow(field.label, editor)
        old = self.scroll.takeWidget()
        if old:
            old.deleteLater()
        self.scroll.setWidget(content)
        self._fill(self._baseline)
        self.feedback.setText("修改后点击保存；切换类别会放弃未保存的编辑。")

    def _fill(self, values: dict) -> None:
        for key, editor in self._editors.items():
            value = values[key]
            if isinstance(editor, QCheckBox):
                editor.setChecked(value)
            elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
                editor.setValue(value)
            elif isinstance(editor, QComboBox):
                editor.setCurrentIndex(editor.findData(value))
            else:
                editor.setText(value)

    def _read(self, editor):
        if isinstance(editor, QCheckBox):
            return editor.isChecked()
        if isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            return editor.value()
        if isinstance(editor, QComboBox):
            return editor.currentData()
        return editor.text().strip()

    def _reset(self) -> None:
        if self._reset_dialog is not None:
            self._reset_dialog.raise_()
            return
        key = self._key
        LOGGER.info("用户请求恢复默认配置：%s，等待确认", key)
        title = self.registry.section(key).title
        dialog = QMessageBox(self)
        dialog.setWindowTitle("恢复默认配置")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        dialog.setText(f"将“{title}”恢复为软件自带默认配置？\n\n"
                       f"会立即覆盖 {key}.json，并放弃当前分类未保存的修改。"
                       "其他分类、日志和数据不受影响。此操作没有自动撤销。")
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        dialog.button(QMessageBox.StandardButton.Yes).setText("恢复默认")
        dialog.button(QMessageBox.StandardButton.Cancel).setText("取消")
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        self._reset_dialog = dialog
        dialog.finished.connect(lambda result: self._finish_reset(key, result))
        dialog.open()

    def _finish_reset(self, key: str, result: int) -> None:
        dialog, self._reset_dialog = self._reset_dialog, None
        if dialog:
            dialog.deleteLater()
        if result != QMessageBox.StandardButton.Yes:
            LOGGER.info("用户取消恢复默认配置：%s", key)
            return
        try:
            self.configuration.restore_defaults(key)
        except (ValueError, OSError) as error:
            self.feedback.setText(f"恢复失败，原配置未改变：{error}")
            return
        if key == self._key:
            self._baseline = self.configuration.get(key)
            self._fill(self._baseline)
            self.feedback.setText("当前分类已恢复默认并保存，无需再次保存。窗口尺寸和启动页面下次启动生效。")

    def _open_configuration(self) -> None:
        LOGGER.info("请求打开配置目录：模块 %s", self._key)
        directory = self.configuration.repository.directory
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            self.feedback.setText(f"已请求打开配置目录，对应文件：{self._key}.json。手动修改文件后请重启应用。")
        else:
            LOGGER.warning("配置目录打开失败：模块 %s", self._key)
            self.feedback.setText(f"无法打开文件夹，请复制上方路径手动访问：{self._key}.json")

    def _save(self) -> None:
        LOGGER.info("用户提交设置表单：%s", self._key)
        values = self.configuration.get(self._key)
        for key, editor in self._editors.items():
            edited = self._read(editor)
            if edited != self._baseline[key]:
                values[key] = edited
        try:
            self.configuration.save(self._key, values)
        except (ValueError, OSError) as error:
            LOGGER.warning("设置保存失败：%s，错误类型 %s", self._key, type(error).__name__)
            self.feedback.setText(f"保存失败：{error}")
            return
        self._baseline = values
        self._fill(values)
        self.feedback.setText("配置已保存。")
