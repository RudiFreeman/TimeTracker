"""Номер версии везде одинаковый. Единственный источник — __version__; остальные места забывали поменять
при выпуске (README на GitHub, CHANGELOG, CLAUDE.md расходились с программой)."""
import os
import re
from datetime import datetime

import pytest

from timetracker import __version__

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSION_RE = r"\d+\.\d+\.\d+"


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


def changelog_versions():
    """(версия, дата) из заголовков «## X.Y.Z — ДД.ММ.ГГГГ», сверху вниз; у самой старой (1.0.0) даты нет."""
    return re.findall(rf"^## ({VERSION_RE})(?: — (\d\d\.\d\d\.\d{{4}}))?\s*$", read("CHANGELOG.md"), re.M)


def test_version_format():
    assert re.fullmatch(VERSION_RE, __version__), __version__


def test_changelog_top_entry_is_current_version():
    versions = changelog_versions()
    assert versions, "в CHANGELOG.md нет заголовков «## X.Y.Z — ДД.ММ.ГГГГ»"
    assert versions[0][0] == __version__, f"верхняя запись CHANGELOG — {versions[0][0]}, а в программе {__version__}"
    assert versions[0][1], "у новой записи CHANGELOG нет даты: «## X.Y.Z — ДД.ММ.ГГГГ»"


def test_changelog_headings_well_formed():
    """Каждый заголовок версии — в нужном формате (иначе «Что нового» и релиз собираются криво)."""
    text = read("CHANGELOG.md")
    for line in re.findall(r"^## .*$", text, re.M):
        assert re.fullmatch(rf"## {VERSION_RE}( — \d\d\.\d\d\.\d{{4}})?\s*", line), f"плохой заголовок: {line!r}"


def test_changelog_newest_first_and_unique():
    versions = changelog_versions()
    numbers = [tuple(map(int, v.split("."))) for v, _ in versions]
    assert numbers == sorted(numbers, reverse=True), "версии в CHANGELOG должны идти от новой к старой"
    assert len(set(numbers)) == len(numbers), "одна и та же версия записана дважды"
    dates = [datetime.strptime(d, "%d.%m.%Y") for _, d in versions if d]
    assert dates == sorted(dates, reverse=True), "даты в CHANGELOG должны идти от новой к старой"


@pytest.mark.parametrize("path, pattern", [
    ("CHANGELOG.md", rf"Текущая версия — v({VERSION_RE})"),
    ("CLAUDE.md", rf"Текущая версия: v({VERSION_RE})"),
])
def test_current_version_lines(path, pattern):
    found = re.findall(pattern, read(path))
    assert found == [__version__], f"{path}: «Текущая версия» = {found}, а в программе {__version__}"


def test_claude_md_history_has_current_version():
    assert re.search(rf"^- v{re.escape(__version__)}, ", read("CLAUDE.md"), re.M), \
        f"в CLAUDE.md, раздел «История», нет строки про v{__version__}"


@pytest.mark.parametrize("path", ["README.md", os.path.join("release", "README.txt"),
                                  os.path.join("release", "UPDATE.txt")])
def test_readmes_have_no_hardcoded_version(path):
    """В README номер не пишем: он устаревает. Версию показывает программа и страница релиза."""
    found = re.findall(rf"\b[vV]?{VERSION_RE}\b", read(path))
    assert not found, f"{path}: в тексте номер версии {found} — уберите (или он должен быть {__version__})"
