"""Текст GitHub Release для текущей версии: «Скачать», «Установка», «Обновление», что не проверено,
«Что нового» (запись CHANGELOG.md). Пишет в stdout; запускается сборкой на GitHub (.github/workflows/build.yml).

Всё после заголовка «## Что нового» программа показывает в окне обновления, поэтому список
непроверенного стоит выше него — коллеги его в программе не видят.

    python -X utf8 tools/release_notes.py [--tag vX.Y.Z]
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from timetracker import __version__  # noqa: E402

CHECK_HEADING = "## Проверка на Windows и Mac"
UNCHECKED = "⬜"
MARKS = ("✅", UNCHECKED, "н/п")


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def changelog_entry(version, text=None):
    """Запись «## X.Y.Z — дата» из CHANGELOG.md до следующей версии, заголовок → «### …»."""
    text = read("CHANGELOG.md") if text is None else text
    match = re.search(rf"^## {re.escape(version)}\b.*?(?=^## |\Z)", text, re.M | re.S)
    if not match:
        raise SystemExit(f"В CHANGELOG.md нет записи «## {version} — ДД.ММ.ГГГГ»")
    return "#" + match.group(0).strip()


def platform_checks(text=None):
    """Строки таблицы «Проверка на Windows и Mac» из QA_CHECKLIST.md: (версия, что, windows, mac)."""
    text = read(os.path.join("tests", "QA_CHECKLIST.md")) if text is None else text
    start = text.find(CHECK_HEADING)
    if start < 0:
        return []
    section = text[start + len(CHECK_HEADING):]
    section = section[:section.find("\n## ")] if "\n## " in section else section
    rows = []
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"\d+\.\d+\.\d+", cells[0]):
            rows.append(tuple(cells))
    return rows


def unchecked(version, rows=None):
    """Что для версии ещё не проверено: [(что, «Windows» / «Mac» / «Windows и Mac»)]."""
    out = []
    for ver, what, win, mac in platform_checks() if rows is None else rows:
        if ver != version:
            continue
        where = [name for name, mark in (("Windows", win), ("Mac", mac)) if mark == UNCHECKED]
        if where:
            out.append((what, " и ".join(where)))
    return out


def notes(version):
    v = version
    parts = [
        f"**Скачать** (в разделе Assets ниже):\n"
        f"- Windows — `TimeTracker-{v}.zip`\n"
        f"- Mac (Apple Silicon, M1 и новее) — `TimeTracker-{v}-mac.dmg`",
        "## Установка\n"
        "**Windows:** распакуйте архив в любую папку с правом записи (например `C:\\TimeTracker`), не в Program Files. "
        "Запустите `TimeTracker.exe`. Если Windows покажет «Система Windows защитила ваш компьютер» → «Подробнее» → "
        "«Выполнить в любом случае» (у программы нет цифровой подписи).\n\n"
        "**Mac:** откройте `.dmg` и перетащите TimeTracker в «Программы». В первый раз macOS не откроет программу "
        "(нет платной подписи Apple): «Системные настройки» → «Конфиденциальность и безопасность» → "
        "«Всё равно открыть». Подробно — README.txt в окне `.dmg`.",
        "## Обновление\n"
        "Программа предложит обновиться сама (раз в день с 9 утра) или нажмите «О программе» → «Проверить обновления». "
        "Данные сохраняются.\n"
        "Со старых версий Windows (2.1.x и раньше): закройте программу (трей → «Выход») и замените `TimeTracker.exe` "
        "новым из архива. База `timetracker.db` рядом с exe сохранится.",
    ]
    todo = unchecked(version)
    if todo:
        parts.append("## ⚠ Не проверено перед выпуском\n"
                     + "\n".join(f"- {what} — **{where}**" for what, where in todo)
                     + "\n\n_Список из таблицы «Проверка на Windows и Mac» в tests/QA_CHECKLIST.md. "
                       "Проверьте и уберите этот раздел перед публикацией._")
    parts.append("## Что нового\n" + changelog_entry(version))
    return "\n\n".join(parts) + "\n"


def main():
    if "--tag" in sys.argv:
        tag = sys.argv[sys.argv.index("--tag") + 1]
        if tag != f"v{__version__}":
            raise SystemExit(f"Тег {tag}, а в программе версия {__version__} — поднимите __version__ или исправьте тег")
    sys.stdout.write(notes(__version__))


if __name__ == "__main__":
    main()
