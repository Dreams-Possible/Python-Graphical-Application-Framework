"""语言无关的消息标识，不依赖 Qt 或资源加载。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    """可重新渲染的消息标识和参数，允许作为状态传递。"""
    key: str
    parameters: tuple[tuple[str, object], ...] = ()


def message(key: str, **parameters) -> Message:
    return Message(key, tuple(parameters.items()))

