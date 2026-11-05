"""错误保留原异常类型和稳定诊断键，展示层单独解析用户消息。"""
from src.shared.messages import message


def ui_error(kind, key, **parameters):
    error = kind(key)
    error.ui_message = message(key, **parameters)
    return error


def error_message(error):
    return getattr(error, "ui_message", str(error))
