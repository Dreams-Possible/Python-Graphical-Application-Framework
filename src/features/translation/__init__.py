"""可切换的在线翻译提供商。"""

from .service import TranslationError, TranslationOptions, Translator, supported_languages

__all__ = ["TranslationError", "TranslationOptions", "Translator", "supported_languages"]
