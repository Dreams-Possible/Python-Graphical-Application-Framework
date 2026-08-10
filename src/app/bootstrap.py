"""在应用入口集中创建并连接对象。"""

from src.features.counter.view import CounterView
from src.features.counter.view_model import CounterViewModel


def create_main_window() -> CounterView:
    """装配计数器功能并返回主窗口。"""
    view_model = CounterViewModel()
    return CounterView(view_model)
