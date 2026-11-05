"""独立当前位置搜索器；选择只回填表单，保存后才应用。"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QListWidget
from src.shared.widgets import plain_label, NavigationDelegate, text_button, text_label


class LocationPicker(QWidget):
    chosen = Signal(object)

    def __init__(self, service, texts, parent=None):
        super().__init__(parent)
        self.texts = texts
        self.service, self.results = service, ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.query = QLineEdit()
        texts.bind_text(self.query, "location.picker.placeholder", setter="setPlaceholderText")
        self.search_button = text_button(texts, "location.picker.search")
        row.addWidget(self.query, 1)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.setObjectName("LocationResults")
        self.list.setItemDelegate(NavigationDelegate(self.list))
        self.list.setMaximumHeight(150)
        self.list.hide()
        layout.addWidget(self.list)
        self.status = text_label(texts, "location.picker.credit", "Muted")
        layout.addWidget(self.status)
        self.search_button.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search_button.click)
        self.list.itemClicked.connect(self.choose)
        self.list.itemActivated.connect(self.choose)
        service.search_finished.connect(self.finished)

    def search(self):
        self.search_button.setEnabled(False)
        self.list.hide()
        self.texts.bind_text(self.status, "location.picker.busy")
        self.service.search(self.query.text())

    def finished(self, results, error):
        self.search_button.setEnabled(True)
        self.results = results
        self.list.clear()
        self.list.addItems([fix.name + " · " + fix.country_code for fix in results])
        self.list.setVisible(bool(results))
        self.texts.set_text(self.status, error) if error else self.texts.bind_text(self.status, "location.picker.choose" if results else "location.picker.empty")

    def choose(self, item):
        index = self.list.row(item)
        if 0 <= index < len(self.results):
            self.chosen.emit(self.results[index])
            self.texts.bind_text(self.status, "location.picker.filled")
