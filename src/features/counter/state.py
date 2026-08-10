"""计数器页面的不可变状态。"""

from dataclasses import dataclass


@dataclass(frozen=True)
class CounterState:
    """描述计数器页面当前应显示的全部业务状态。"""

    count: int
    message: str
    can_reset: bool
