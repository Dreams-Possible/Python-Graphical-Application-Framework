"""计数器页面状态管理者。"""

from PySide6.QtCore import QObject, Signal, Slot

from src.features.counter.state import CounterState


class CounterViewModel(QObject):
    """接收用户操作并向 View 公开只读页面状态。"""

    state_changed = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self._state = self._create_state(0)

    @property
    def state(self) -> CounterState:
        """返回当前页面状态。"""
        return self._state

    @Slot()
    def increment(self) -> None:
        """响应用户操作并增加计数。"""
        self._set_count(self._state.count + 1)

    @Slot()
    def reset(self) -> None:
        """将计数恢复到初始状态。"""
        self._set_count(0)

    def _set_count(self, count: int) -> None:
        self._state = self._create_state(count)
        self.state_changed.emit(self._state)

    @staticmethod
    def _create_state(count: int) -> CounterState:
        message = "点击按钮开始计数" if count == 0 else f"已点击 {count} 次"
        return CounterState(
            count=count,
            message=message,
            can_reset=count > 0,
        )
