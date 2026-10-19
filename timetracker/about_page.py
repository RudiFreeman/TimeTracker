"""Страница «О программе»: иконка, название, версия, автор, обновления и история версий из CHANGELOG.md."""
import os
import platform
import sys
from urllib.parse import quote

from PySide6 import __version__ as pyside_version
from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QTextBrowser, QVBoxLayout, QWidget

from . import __version__, theme, update_dialog

AUTHOR = "Алексей Рудович"
REPO_URL = "https://github.com/RudiFreeman/TimeTracker"
# Google Form of the author: bugs and ideas. Opens in the browser — the program itself sends nothing.
FEEDBACK_URL = "https://docs.google.com/forms/d/e/1FAIpQLSdXuzbhMWoMrutEENDCZNALxK_syX_CKRDTYHOPGBzejPS1RA/viewform"
# "entry.<id>" of the form's «Версия программы» question: filled in for the user. None — the form has none yet.
FEEDBACK_VERSION_FIELD = None
LICENSE_TEXT = (f'Бесплатная программа с открытым кодом, лицензия MIT · <a href="{REPO_URL}">исходный код на GitHub</a>. '
                'Qt / PySide6 — под лицензией <a href="https://www.qt.io/qt-for-python">LGPL v3</a>.')
PRIVACY_TEXT = ("Ваши данные никуда не отправляются: всё хранится в файле timetracker.db "
                f"{'на этом Mac' if theme.MAC else 'рядом с программой'}. "
                "В интернет программа ходит только чтобы проверить обновления на GitHub.")
DESCRIPTION = ("Портативный трекер рабочего времени для монтажёра и продюсера контента: таймер по задачам "
               "и подзадачам, журнал по дням, сводка по задачам и учёт токенов AI-сервисов.")
# CHANGELOG.md лежит в корне проекта; в exe build.bat кладёт его в корень сборки — путь тот же.
CHANGELOG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "CHANGELOG.md")


def feedback_url():
    if not FEEDBACK_VERSION_FIELD:
        return FEEDBACK_URL
    version = f"Time Tracker {__version__} ({'Mac' if theme.MAC else 'Windows'})"
    return f"{FEEDBACK_URL}?usp=pp_url&{FEEDBACK_VERSION_FIELD}={quote(version)}"


def open_feedback():
    QDesktopServices.openUrl(QUrl(feedback_url()))


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
    def __init__(self, timer):
        super().__init__()
        self.timer = timer
        self.updater = timer.updater
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
            f"Иконки — {'Fluent UI System Icons (MIT)' if theme.MAC else 'Segoe MDL2 Assets'}.",
            objectName="hint", wordWrap=True))
        license_label = QLabel(LICENSE_TEXT, objectName="hint", wordWrap=True, openExternalLinks=True)
        license_label.setTextFormat(Qt.RichText)
        layout.addWidget(license_label)
        layout.addWidget(QLabel(PRIVACY_TEXT, objectName="hint", wordWrap=True))

        row = QHBoxLayout()
        copy = QPushButton("Скопировать версию")
        copy.clicked.connect(lambda: QApplication.clipboard().setText(f"Time Tracker {__version__}"))
        row.addWidget(copy)
        feedback = QPushButton("Обратная связь", toolTip="Нашли ошибку или есть идея — напишите автору")
        feedback.clicked.connect(open_feedback)
        row.addWidget(feedback)
        self.update_btn = QPushButton(objectName="accent")
        self.update_btn.clicked.connect(self._on_update)
        row.addWidget(self.update_btn)
        self.update_status = QLabel(objectName="hint")
        row.addWidget(self.update_status)
        row.addStretch(1)
        layout.addLayout(row)
        self.updater.checked.connect(self._show_update)
        self.updater.prepared.connect(lambda new, error: self._show_update(None, "", error))
        self._show_update(None, "")

        layout.addSpacing(10)
        layout.addWidget(QLabel("Что нового", objectName="section"))
        history = QTextBrowser(objectName="plain", openExternalLinks=False)
        history.setMarkdown(changelog_markdown())
        history.document().setDocumentMargin(12)
        layout.addWidget(history, 1)

    def _show_update(self, _release, error, install_error=""):
        """Button + hint by the result of the last check (the startup one or «Проверить»)."""
        new = self.updater.update_available()
        if self.updater.downloading:
            text, hint = f"Обновить до {new.label}" if new else "Проверить обновления", "Скачиваю обновление…"
        elif self.updater.checking:
            text, hint = "Проверить обновления", "Проверяю…"
        elif new:
            text, hint = f"Обновить до {new.label}", "Вышла новая версия"
        elif error:
            text, hint = "Проверить обновления", f"Не удалось проверить: {error}"
        elif self.updater.latest:
            text, hint = "Проверить обновления", "У вас последняя версия"
        else:
            text, hint = "Проверить обновления", ""
        self.update_btn.setText(text)
        self.update_btn.setObjectName("accent" if new else "")
        self.update_btn.style().unpolish(self.update_btn)
        self.update_btn.style().polish(self.update_btn)
        self.update_btn.setEnabled(not self.updater.busy)
        if install_error and not self.updater.busy:
            hint = f"Не получилось обновить: {install_error}"
        self.update_status.setText(hint)

    def _on_update(self):
        new = self.updater.update_available()
        if new:
            update_dialog.offer(self.window(), self.timer, new)
        else:
            self.updater.check()
            self._show_update(None, "")

    def refresh(self):
        self._show_update(None, "")
