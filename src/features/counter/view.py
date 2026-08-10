"""计数器功能的 Qt 界面。"""

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from src.features.counter.state import CounterState
from src.features.counter.view_model import CounterViewModel


class CounterView(QWidget):
    """根据 CounterState 渲染界面并转发用户操作。"""

    def __init__(self, view_model: CounterViewModel) -> None:
        super().__init__()
        self._view_model = view_model

        self.setWindowTitle("Python + Qt 架构 Demo")
        self.resize(420, 260)

        self._title_label = QLabel("功能模块化 Qt Demo")
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._count_label = QLabel()
        self._count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._message_label = QLabel()
        self._message_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._increment_button = QPushButton("增加")
        self._reset_button = QPushButton("重置")

        layout = QVBoxLayout(self)
        layout.addStretch()
        layout.addWidget(self._title_label)
        layout.addWidget(self._count_label)
        layout.addWidget(self._message_label)
        layout.addWidget(self._increment_button)
        layout.addWidget(self._reset_button)
        layout.addStretch()

        self._increment_button.clicked.connect(self._view_model.increment)
        self._reset_button.clicked.connect(self._view_model.reset)
        self._view_model.state_changed.connect(self._render)

        self._render(self._view_model.state)

    @Slot(object)
    def _render(self, state: CounterState) -> None:
        """把完整页面状态映射到 Qt 控件。"""
        self._count_label.setText(str(state.count))
        self._message_label.setText(state.message)
        self._reset_button.setEnabled(state.can_reset)
