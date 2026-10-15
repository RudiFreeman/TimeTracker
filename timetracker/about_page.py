"""Страница «О программе»: иконка, название, версия, автор и история версий из CHANGELOG.md."""
import os
import platform
import sys

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from . import __version__, theme

AUTHOR = "Алексей Рудович"
DESCRIPTION = ("Портативный трекер рабочего времени для монтажёра и продюсера контента: таймер по продуктам "
               "и подзадачам, журнал по дням, сводка по продуктам и учёт токенов AI-сервисов.")
# CHANGELOG.md лежит в корне проекта; в exe build.bat кладёт его в корень сборки — путь тот же.
CHANGELOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CHANGELOG.md")


def changelog_markdown():
    """Версии из CHANGELOG.md без шапки файла (всё до первого «## »)."""
    try:
        with open(CHANGELOG, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return "История версий недоступна."
    start = text.find("\n## ")
    text = text[start + 1:] if start >= 0 else text
    return text.replace("## ", "#### ")  # заголовки версий помельче


class AboutPage(QWidget):
    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 14)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(18)
        icon = QLabel()
        icon.setPixmap(theme.app_icon().pixmap(QSize(80, 80)))
        head.addWidget(icon, 0, Qt.AlignTop)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(QLabel("Time Tracker", objectName="title"))
        bits = "64-бит" if sys.maxsize > 2**32 else "32-бит"
        version = QLabel(f"Версия {__version__} · {bits}", objectName="secondary")
        version.setTextInteractionFlags(Qt.TextSelectableByMouse)
        names.addWidget(version)
        names.addSpacing(8)
        names.addWidget(QLabel(DESCRIPTION, wordWrap=True))
        head.addLayout(names, 1)
        layout.addLayout(head)

        layout.addSpacing(6)
        layout.addWidget(QLabel(f"Автор: {AUTHOR}", objectName="secondary"))
        layout.addWidget(QLabel(
            f"Сделано на Python {platform.python_version()} · Qt / PySide6 {pyside_version} · SQLite. "
            "Иконки — Segoe MDL2 Assets.", objectName="hint", wordWrap=True))

        row = QHBoxLayout()
        copy = QPushButton("Скопировать версию")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(f"Time Tracker {__version__}"))
        row.addWidget(copy)
        row.addStretch(1)
        layout.addLayout(row)

        layout.addSpacing(10)
        layout.addWidget(QLabel("Что нового", objectName="section"))
        history = QTextBrowser(objectName="plain", openExternalLinks=False)
        history.setMarkdown(changelog_markdown())
        history.document().setDocumentMargin(12)
        layout.addWidget(history, 1)

    def refresh(self):
        pass
