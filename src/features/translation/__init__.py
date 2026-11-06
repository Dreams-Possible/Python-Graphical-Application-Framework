"""可切换的在线翻译提供商。"""

from .service import TranslationError, TranslationOptions, TranslationResult, Translator, supported_languages

__all__ = ["TranslationError", "TranslationOptions", "TranslationResult", "Translator", "supported_languages"]
