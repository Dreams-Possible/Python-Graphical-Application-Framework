"""从设置注册信息生成表单；保存时只合并用户实际修改的字段。"""

import logging

from PySide6.QtCore import QSize, Qt, QUrl
from src.shared.ui_metrics import UI
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
    def __init__(self, registry: SettingsRegistry, configuration: Configuration, storage: StorageViewModel, location=None) -> None:
        super().__init__()
        self.registry, self.configuration = registry, configuration
        self.location_service = location
        if location:
            location.status_changed.connect(self._location_status_changed)
        self._key = ""
        self._editors = {}
        self._baseline = {}
        self._reset_dialog = None
        layout = page_layout(self, "设置", "调整外观与功能偏好，保存后自动记住你的选择。")
        body = QHBoxLayout()
        self.categories = QListWidget()
        self.categories.setObjectName("SettingsCategories")
        self.categories.setFixedWidth(UI.settings_categories_width)
        self.categories.setItemDelegate(NavigationDelegate(self.categories))
        self.categories.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.categories.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.categories.addItems([section.title for section in registry.sections] + ["本地文件"])
        for index in range(self.categories.count()):
            self.categories.item(index).setSizeHint(QSize(0, UI.navigation_height))
        self.pages = QStackedWidget()
        form_page = QWidget()
        form_layout = QVBoxLayout(form_page)
        form_layout.setContentsMargins(12, 0, 0, 0)
        self.description = plain_label(name="Muted")
        form_layout.addWidget(self.description)
        self.open_configuration = QPushButton("打开配置位置")
        self.open_configuration.clicked.connect(self._open_configuration)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        form_layout.addWidget(self.scroll, 1)
        self.configuration_path = plain_label(name="Muted")
        form_layout.addWidget(self.configuration_path)
        self.feedback = plain_label(name="Muted")
        form_layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        reset = QPushButton("恢复当前分类默认配置")
        reset.clicked.connect(self._reset)
        save = QPushButton("保存设置")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        actions.addWidget(self.open_configuration)
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
        self.description.setText(section.description)
        self.configuration_path.setText(f"配置文件：{path}")
        self.open_configuration.setToolTip(f"打开 {path.name} 所在文件夹")
        self._baseline = self.configuration.get(section.key)
        self._editors = {}
        content = QWidget()
        content.setObjectName("SettingsForm")
        form = QFormLayout(content)
        form.setContentsMargins(16, 20, 16, 20)
        form.setSpacing(16)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        if section.key == "location":
            self._location_form = form
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
            if section.key == "location" and field.key == "mode" and self.location_service:
                from src.features.location.picker import LocationPicker
                self.location_hint = plain_label(name="Muted")
                self.location_status = plain_label(name="Muted")
                form.addRow(self.location_hint)
                form.addRow(self.location_status)
                self.refresh_location = QPushButton("重新通过 IP 定位")
                self.refresh_location.clicked.connect(self._refresh_network_location)
                form.addRow(self.refresh_location)
                self.location_picker = LocationPicker(self.location_service)
                self.location_picker.chosen.connect(self._choose_location)
                form.addRow(self.location_picker)
        old = self.scroll.takeWidget()
        if old:
            old.deleteLater()
        self.scroll.setWidget(content)
        self._fill(self._baseline)
        if section.key == "location":
            self._editors["mode"].currentIndexChanged.connect(self._location_mode_changed)
            self._editors["enabled"].toggled.connect(self._location_mode_changed)
            self._editors["endpoint"].textChanged.connect(self._location_mode_changed)
            self._editors["timeout_seconds"].valueChanged.connect(self._location_mode_changed)
            self._location_mode_changed()
        self.feedback.setText("修改后点击保存；切换类别会放弃未保存的编辑。")

    def _location_status_changed(self, message):
        if self._key == "location":
            self._location_mode_changed()

    def _location_mode_changed(self, *_):
        if self._key != "location":
            return
        manual = self._editors["mode"].currentData() == "manual"
        enabled = self._editors["enabled"].isChecked()
        form = self._location_form
        for key, editor in self._editors.items():
            if key.startswith("manual_") or key == "geocoding_url":
                form.setRowVisible(editor, enabled and manual)
            elif key == "endpoint":
                form.setRowVisible(editor, enabled and not manual)
            elif key in ("use_for_clock", "timeout_seconds"):
                form.setRowVisible(editor, enabled)
        if not self.location_service:
            return
        form.setRowVisible(self.location_picker, enabled and manual)
        form.setRowVisible(self.refresh_location, enabled and not manual)
        saved = self.configuration.get("location")
        same_mode = saved["enabled"] == enabled and saved["mode"] == self._editors["mode"].currentData()
        clean_network = same_mode and all(self._read(self._editors[key]) == saved[key] for key in ("endpoint", "timeout_seconds"))
        self.refresh_location.setEnabled(enabled and not manual and clean_network)
        self.refresh_location.setToolTip("使用已保存的接口，通过当前网络出口 IP 定位" if clean_network else "请先保存位置来源及网络配置")
        if not enabled:
            self.location_hint.setText("保存后停用当前位置，日历不再按位置加载节假日。")
        elif manual:
            self.location_hint.setText("搜索并选择城市，下方位置字段会自动填写；点击保存后应用。")
        else:
            self.location_hint.setText("通过网络请求的出口 IP 判断位置，代理可能影响结果。保存后自动定位；失败时可点击下方按钮重试。")
        if not same_mode or (not manual and not clean_network):
            self.location_status.setText("位置配置尚未保存，点击底部“保存设置”后生效。")
        else:
            self.location_status.setText(self.location_service.status)

    def _refresh_network_location(self):
        self._location_mode_changed()
        if self.refresh_location.isEnabled():
            self.location_service.refresh()

    def _choose_location(self, fix):
        if self._key != "location":
            return
        values = {"manual_name": fix.name, "manual_country": fix.country_code,
                  "manual_latitude": fix.latitude, "manual_longitude": fix.longitude,
                  "manual_timezone": fix.timezone}
        for key, value in values.items():
            editor = self._editors[key]
            editor.setValue(value) if isinstance(editor, QDoubleSpinBox) else editor.setText(value)
        self._editors["mode"].setCurrentIndex(self._editors["mode"].findData("manual"))

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
        if self._key == "location":
            self._location_mode_changed()

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
            if self._key == "location" and values["enabled"] and values["mode"] == "manual":
                from src.features.location.service import manual_location
                manual_location(values)
            self.configuration.save(self._key, values)
        except (ValueError, OSError) as error:
            LOGGER.warning("设置保存失败：%s，错误类型 %s", self._key, type(error).__name__)
            self.feedback.setText(f"保存失败：{error}")
            return
        self._baseline = values
        self._fill(values)
        self.feedback.setText("配置已保存。")
