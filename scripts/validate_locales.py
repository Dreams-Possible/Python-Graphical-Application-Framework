"""校验语言资源和源码中的静态引用；不启动 GUI、不访问网络。"""
import ast
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.shared.localization import load_catalog, placeholders


def validate():
    catalogs = {language: load_catalog(ROOT / "assets" / "locales" / language) for language in ("zh-CN", "en-US")}
    baseline = catalogs["zh-CN"]
    for language, entries in catalogs.items():
        if entries.keys() != baseline.keys():
            raise ValueError(f"{language}: missing={baseline.keys() - entries.keys()}, extra={entries.keys() - baseline.keys()}")
        for key, value in entries.items():
            if placeholders(value) != placeholders(baseline[key]):
                raise ValueError(f"{language}: placeholder mismatch for {key}")
    references = 0
    for path in (ROOT / "src").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for call in ast.walk(tree):
            if not isinstance(call, ast.Call):
                continue
            key_index = None
            if isinstance(call.func, ast.Name):
                if call.func.id in ("message", "msg", "Message"):
                    key_index = 0
                elif call.func.id in ("text_button", "text_label", "ui_error"):
                    key_index = 1
            elif isinstance(call.func, ast.Attribute):
                target = call.func.value
                is_texts = (isinstance(target, ast.Name) and target.id == "texts") or (isinstance(target, ast.Attribute) and target.attr == "texts")
                if is_texts and call.func.attr in ("get", "bind_text"):
                    key_index = 0 if call.func.attr == "get" else 1
            if key_index is None or len(call.args) <= key_index:
                continue
            key = call.args[key_index]
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if key.value not in baseline and key.value + ".other" not in baseline:
                raise ValueError(f"{path.relative_to(ROOT)}:{call.lineno}: unknown resource {key.value}")
            references += 1
    print(f"Validated {len(catalogs)} languages, {len(baseline)} keys each, {references} static references")


if __name__ == "__main__":
    validate()
