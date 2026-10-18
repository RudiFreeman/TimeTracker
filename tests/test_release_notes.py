"""Текст релиза собирается сборкой на GitHub (tools/release_notes.py): «Что нового» из CHANGELOG и список
непроверенного из таблицы «Проверка на Windows и Mac» в QA_CHECKLIST.md."""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tools"))
import release_notes  # noqa: E402

from timetracker import __version__  # noqa: E402


def test_check_table_well_formed():
    """Каждая строка таблицы — версия и отметки ✅ / ⬜ / н/п (иначе непроверенное не попадёт в релиз)."""
    rows = release_notes.platform_checks()
    assert rows, "в tests/QA_CHECKLIST.md нет таблицы «Проверка на Windows и Mac»"
    for ver, what, win, mac in rows:
        assert what and win in release_notes.MARKS and mac in release_notes.MARKS, (ver, what, win, mac)


def test_unchecked_lists_only_this_version():
    rows = [("2.4.0", "Выход", "⬜", "✅"), ("2.4.0", "Автозапуск", "⬜", "⬜"), ("2.4.0", "Значок", "н/п", "✅"),
            ("2.3.2", "Старое", "⬜", "⬜")]
    assert release_notes.unchecked("2.4.0", rows) == [("Выход", "Windows"), ("Автозапуск", "Windows и Mac")]


def test_notes_have_both_files_and_whats_new_last():
    """Всё после «## Что нового» программа показывает в окне обновления — список непроверенного выше него."""
    text = release_notes.notes(__version__)
    assert f"TimeTracker-{__version__}.zip" in text and f"TimeTracker-{__version__}-mac.dmg" in text
    head, _, tail = text.partition("## Что нового\n")
    assert tail.startswith(f"### {__version__} — ") and "Не проверено" not in tail


def test_tag_must_match_version(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["release_notes.py", "--tag", "v0.0.1"])
    with pytest.raises(SystemExit):
        release_notes.main()
