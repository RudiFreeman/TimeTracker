"""Тексты интерфейса: после 2.3.0 в UI нет слова «продукт» (теперь «Задача»).

Проверяются только строки в коде (не комментарии): в коде и базе по-прежнему product — это нормально.
"""
import io
import pathlib
import tokenize

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCES = sorted((ROOT / "timetracker").glob("*.py")) + [ROOT / "main.py"]


def ui_strings(path):
    with open(path, encoding="utf-8") as f:
        for tok in tokenize.generate_tokens(io.StringIO(f.read()).readline):
            if tok.type == tokenize.STRING or tok.type == getattr(tokenize, "FSTRING_MIDDLE", -1):
                yield tok.start[0], tok.string


def test_no_word_product_in_ui():
    found = [f"{p.name}:{line}: {text}" for p in SOURCES for line, text in ui_strings(p) if "родукт" in text]
    assert found == []
