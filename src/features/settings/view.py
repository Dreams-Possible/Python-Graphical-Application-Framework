"""从设置注册信息生成表单；保存时只合并用户实际修改的字段。"""

from src.shared.errors import error_message

import logging

from PySide6.QtCore import QSignalBlocker, QSize, Qt, QUrl
from src.shared.ui_metrics import UI
from src.shared.gestures import KineticScrollArea
from src.shared.localization import message
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from src.features.settings.storage import StorageView, StorageViewModel
from src.shared.configuration import Configuration, SettingsRegistry
from src.shared.widgets import NavigationDelegate, choice_box, page_layout, plain_label, text_button

LOGGER = logging.getLogger("workbench.settings")


class SettingsView(QWidget):
    def __init__(self, registry: SettingsRegistry, configuration: Configuration, storage: StorageViewModel, texts, location=None) -> None:
        super().__init__()
        self.texts = texts
        self.registry, self.configuration = registry, configuration
        self.location_service = location
        if location:
            location.status_changed.connect(self._location_status_changed)
        self._key = ""
        self._editors = {}
        self._baseline = {}
        self._reset_dialog = None
        layout = page_layout(self, "settings.page.title", "settings.page.subtitle", texts=texts)
        body = QHBoxLayout()
        self.categories = QListWidget()
        self.categories.setObjectName("SettingsCategories")
        self.categories.setFixedWidth(UI.settings_categories_width)
        self.categories.setItemDelegate(NavigationDelegate(self.categories))
        self.categories.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.categories.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.categories.addItems([texts.get(section.title_key) for section in registry.sections] + [texts.get("settings.local_files")])
        for index in range(self.categories.count()):
            self.categories.item(index).setSizeHint(QSize(0, UI.navigation_height))
        self.pages = QStackedWidget()
        form_page = QWidget()
        form_layout = QVBoxLayout(form_page)
        form_layout.setContentsMargins(12, 0, 0, 0)
        self.description = plain_label(name="Muted")
        form_layout.addWidget(self.description)
        self.open_configuration = text_button(texts, "settings.open_config")
        self.open_configuration.clicked.connect(self._open_configuration)
        self.scroll = KineticScrollArea()
        self.scroll.setWidgetResizable(True)
        form_layout.addWidget(self.scroll, 1)
        self.configuration_path = plain_label(name="Muted")
        form_layout.addWidget(self.configuration_path)
        self.feedback = plain_label(name="Muted")
        form_layout.addWidget(self.feedback)
        actions = QHBoxLayout()
        reset = text_button(texts, "settings.reset_category")
        reset.clicked.connect(self._reset)
        save = text_button(texts, "common.save")
        save.setObjectName("Primary")
        save.clicked.connect(self._save)
        actions.addWidget(self.open_configuration)
        actions.addWidget(reset)
        actions.addStretch()
        actions.addWidget(save)
        form_layout.addLayout(actions)
        self.storage = StorageView(storage, texts)
        self.pages.addWidget(form_page)
        self.pages.addWidget(self.storage)
        body.addWidget(self.categories)
        body.addWidget(self.pages, 1)
        layout.addLayout(body, 1)
        self.categories.currentRowChanged.connect(self._select)
        self.categories.setCurrentRow(0)
        texts.changed.connect(self.retranslate)

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
        self.texts.bind_text(self.description, section.description_key)
        self.texts.bind_text(self.configuration_path, "settings.path", path=str(path))
        self.texts.bind_text(self.open_configuration, "settings.open_hint", setter="setToolTip", name=path.name)
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
        if section.key == "translation":
            self._translation_form = form
        for field in section.fields:
            if field.kind == "bool":
                editor = QCheckBox()
                self.texts.bind_text(editor, "settings.enabled")
            elif field.kind in ("int", "float"):
                editor = QSpinBox() if field.kind == "int" else QDoubleSpinBox()
                if field.kind == "float":
                    editor.setDecimals(5)
                editor.setRange(field.minimum, field.maximum)
            elif field.kind == "choice":
                editor = choice_box()
                for value, label in field.choices:
                    editor.addItem(self.texts.get(label), value)
            else:
                editor = QLineEdit()
                if field.kind == "secret":
                    editor.setEchoMode(QLineEdit.EchoMode.Password)
            self.texts.bind_text(editor, field.hint_key, setter="setToolTip") if field.hint_key else editor.setToolTip("")
            self.texts.bind_text(editor, field.label_key, setter="setAccessibleName")
            self._editors[field.key] = editor
            field_label = QLabel()
            self.texts.bind_text(field_label, field.label_key)
            form.addRow(field_label, editor)
            if section.key == "translation" and field.key == "provider":
                self.translation_hint = plain_label(name="Muted")
                form.addRow(self.translation_hint)
                docs = text_button(self.texts, "translation.open_docs")
                docs.clicked.connect(self._open_translation_docs)
                form.addRow(docs)
            if section.key == "location" and field.key == "mode" and self.location_service:
                from src.features.location.picker import LocationPicker
                self.location_hint = plain_label(name="Muted")
                self.location_status = plain_label(name="Muted")
                form.addRow(self.location_hint)
                form.addRow(self.location_status)
                self.refresh_location = text_button(self.texts, "settings.retry_ip")
                self.refresh_location.clicked.connect(self._refresh_network_location)
                form.addRow(self.refresh_location)
                self.location_picker = LocationPicker(self.location_service, self.texts)
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
        if section.key == "translation":
            self._editors["provider"].currentIndexChanged.connect(self._translation_provider_changed)
            self._translation_provider_changed()
        self.texts.bind_text(self.feedback, "settings.edit_hint")

    def retranslate(self):
        blocker = QSignalBlocker(self.categories)
        for index, section in enumerate(self.registry.sections):
            self.categories.item(index).setText(self.texts.get(section.title_key))
        self.categories.item(len(self.registry.sections)).setText(self.texts.get("settings.local_files"))
        if not self._key:
            return
        for field in self.registry.section(self._key).fields:
            editor = self._editors[field.key]
            if field.kind == "choice":
                blocked = QSignalBlocker(editor)
                for index, (value, key) in enumerate(field.choices):
                    editor.setItemText(index, self.texts.get(key))
                del blocked

    def _translation_provider_changed(self, *_):
        if self._key != "translation":
            return
        provider = self._editors["provider"].currentData()
        for key, editor in self._editors.items():
            if key not in ("provider", "timeout_seconds", "max_workers"):
                self._translation_form.setRowVisible(editor, key.startswith(provider + "_"))
        self.texts.bind_text(self.translation_hint, "translation.hint." + provider)

    def _open_translation_docs(self):
        urls = {"mymemory": "https://mymemory.translated.net/doc/spec.php",
                "google": "https://cloud.google.com/translate/docs/setup",
                "baidu": "https://fanyi-api.baidu.com/doc/21",
                "youdao": "https://ai.youdao.com/DOCSIRMA/html/trans/api/wbfy/index.html",
                "libre": "https://docs.libretranslate.com/"}
        QDesktopServices.openUrl(QUrl(urls[self._editors["provider"].currentData()]))

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
        self.texts.bind_text(self.refresh_location, "settings.ip_saved" if clean_network else "settings.ip_save_first", setter="setToolTip")
        if not enabled:
            self.texts.bind_text(self.location_hint, "settings.location_disabled")
        elif manual:
            self.texts.bind_text(self.location_hint, "settings.location_manual")
        else:
            self.texts.bind_text(self.location_hint, "settings.location_network")
        if not same_mode or (not manual and not clean_network):
            self.texts.bind_text(self.location_status, "settings.location_unsaved")
        else:
            self.texts.set_text(self.location_status, self.location_service.status)

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
        if self._key == "translation":
            self._translation_provider_changed()

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
        title = message(self.registry.section(key).title_key)
        dialog = QMessageBox(self)
        self.texts.bind_text(dialog, "settings.reset.title", setter="setWindowTitle")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setTextFormat(Qt.TextFormat.PlainText)
        self.texts.bind_text(dialog, "settings.reset.prompt", title=title, file_key=key)
        dialog.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        self.texts.bind_text(dialog.button(QMessageBox.StandardButton.Yes), "settings.reset.confirm")
        self.texts.bind_text(dialog.button(QMessageBox.StandardButton.Cancel), "common.cancel")
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
            self.texts.bind_text(self.feedback, "settings.reset.failed", detail=error_message(error))
            return
        if key == self._key:
            self._baseline = self.configuration.get(key)
            self._fill(self._baseline)
            self.texts.bind_text(self.feedback, "settings.reset.done")

    def _open_configuration(self) -> None:
        LOGGER.info("请求打开配置目录：模块 %s", self._key)
        directory = self.configuration.repository.directory
        if QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory))):
            self.texts.bind_text(self.feedback, "settings.open.done", file_key=self._key)
        else:
            LOGGER.warning("配置目录打开失败：模块 %s", self._key)
            self.texts.bind_text(self.feedback, "settings.open.failed", file_key=self._key)

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
            if self._key == "translation":
                from src.features.translation.service import TranslationOptions, validate_options
                validate_options(TranslationOptions.from_values(values))
            self.configuration.save(self._key, values)
        except (ValueError, OSError) as error:
            LOGGER.warning("设置保存失败：%s，错误类型 %s", self._key, type(error).__name__)
            self.texts.bind_text(self.feedback, "settings.save.failed", detail=error_message(error))
            return
        self._baseline = values
        self._fill(values)
        self.texts.bind_text(self.feedback, "settings.save.done")
