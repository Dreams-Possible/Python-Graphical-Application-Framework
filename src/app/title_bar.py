"""单行窗口顶栏：品牌、菜单与窗口控制，共用应用主题。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSizePolicy, QWidget, QHBoxLayout, QLabel, QMenuBar, QPushButton
from version import APP_VERSION
from src.shared.ui_metrics import UI


class TitleBar(QWidget):
    def __init__(self, window, texts):
        super().__init__(window)
        self.host = window
        self._press_global = None
        self._drag_offset = None
        self._system_drag = False
        self.setObjectName("TitleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(UI.title_height)
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 0, 0)
        row.setSpacing(8)
        name = QLabel()
        texts.bind_text(name, "app.brand")
        name.setObjectName("WindowBrand")
        version = QLabel(APP_VERSION)
        version.setObjectName("Muted")
        for label in (name, version):
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            label.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            row.addWidget(label, 0, Qt.AlignmentFlag.AlignVCenter)
        self.menu = QMenuBar()
        self.menu.setNativeMenuBar(False)
        self.menu.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        row.addWidget(self.menu, 0, Qt.AlignmentFlag.AlignVCenter)
        row.addStretch()
        for text, title, callback in (("−", "app.minimize", window.showMinimized),
                                      ("□", "app.maximize_restore", self.toggle_maximized),
                                      ("×", "app.close_window", window.close)):
            button = QPushButton(text)
            button.setObjectName("WindowClose" if text == "×" else "WindowControl")
            button.setFixedSize(UI.window_button_width, UI.title_height)
            texts.bind_text(button, title, setter="setToolTip")
            texts.bind_text(button, title, setter="setAccessibleName")
            button.clicked.connect(callback)
            row.addWidget(button)

    def toggle_maximized(self):
        self.host.showNormal() if self.host.isMaximized() else self.host.showMaximized()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = event.globalPosition().toPoint()
            self._drag_offset = self._press_global - self.host.frameGeometry().topLeft()
            self._system_drag = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._press_global is None or not event.buttons() & Qt.MouseButton.LeftButton:
            return super().mouseMoveEvent(event)
        point = event.globalPosition().toPoint()
        if (point - self._press_global).manhattanLength() < QApplication.startDragDistance():
            return
        if not self._system_drag:
            handle = self.host.windowHandle()
            if handle and handle.startSystemMove():
                self._system_drag = True
                self._press_global = None
                return
            if self.host.isMaximized():
                self.host.showNormal()
                self._drag_offset.setX(self.host.width() // 2)
        self.host.move(point - self._drag_offset)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._press_global = None
        self._system_drag = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_global = None
            self.toggle_maximized()
            event.accept()
        else:
            super().mouseDoubleClickEvent(event)
