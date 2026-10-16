"""Общая настройка pytest.

- Корень проекта в sys.path — чтобы работал `import timetracker`.
- Qt без окон на экране (offscreen) — GUI-тесты не мигают и не зависят от монитора.
- Каждый тест получает свою пустую базу во временной папке: рабочая база не трогается.
"""
import os
import sys
from datetime import datetime

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from timetracker.db import Database  # noqa: E402

DAY = datetime(2026, 10, 14)  # среда; все времена в тестах — от этой даты


def at(hour, minute=0, second=0, day=0):
    """Момент времени тестового дня: at(9, 30) -> 14.10.2026 09:30, day=1 -> следующий день."""
    return DAY.replace(day=DAY.day + day, hour=hour, minute=minute, second=second)


@pytest.fixture
def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    yield database
    database.close()


@pytest.fixture
def pair(db):
    """Создаёт задачу + подзадачу и возвращает их id: pair("DAC 520SV", "Съемка")."""
    def make(product, subtask="Without task"):
        return db.get_or_create_product(product), db.create_subtask(subtask)
    return make


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    from timetracker import theme
    app = QApplication.instance() or QApplication([])
    app.setStyle("Fusion")
    app.setStyleSheet(theme.stylesheet())
    return app
