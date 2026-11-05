"""独立当前位置搜索器；选择只回填表单，保存后才应用。"""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QListWidget
from src.shared.widgets import plain_label, NavigationDelegate


class LocationPicker(QWidget):
    chosen = Signal(object)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service, self.results = service, ()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        row = QHBoxLayout()
        self.query = QLineEdit()
        self.query.setPlaceholderText("搜索当前位置，例如 上海、Tokyo、London")
        self.search_button = QPushButton("搜索城市")
        row.addWidget(self.query, 1)
        row.addWidget(self.search_button)
        layout.addLayout(row)
        self.list = QListWidget()
        self.list.setObjectName("LocationResults")
        self.list.setItemDelegate(NavigationDelegate(self.list))
        self.list.setMaximumHeight(150)
        self.list.hide()
        layout.addWidget(self.list)
        self.status = plain_label("搜索结果由 Open-Meteo / GeoNames 提供，选择后点击保存。", "Muted")
        layout.addWidget(self.status)
        self.search_button.clicked.connect(self.search)
        self.query.returnPressed.connect(self.search_button.click)
        self.list.itemClicked.connect(self.choose)
        self.list.itemActivated.connect(self.choose)
        service.search_finished.connect(self.finished)

    def search(self):
        self.search_button.setEnabled(False)
        self.list.hide()
        self.status.setText("正在搜索…")
        self.service.search(self.query.text())

    def finished(self, results, error):
        self.search_button.setEnabled(True)
        self.results = results
        self.list.clear()
        self.list.addItems([fix.name + " · " + fix.country_code for fix in results])
        self.list.setVisible(bool(results))
        self.status.setText(error or ("请选择地点，保存后应用。" if results else "未找到地点，请换个名称。"))

    def choose(self, item):
        index = self.list.row(item)
        if 0 <= index < len(self.results):
            self.chosen.emit(self.results[index])
            self.status.setText("已回填位置，点击保存后应用。")
