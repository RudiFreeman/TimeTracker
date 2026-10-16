"""Страница «О программе»: лицензия, ссылка на код, приватность."""
import os

from PySide6.QtWidgets import QLabel

from timetracker import about_page, updater
from timetracker.about_page import AboutPage
from timetracker.timer_window import Hub, TimerWindow


def test_about_shows_license_and_privacy(qapp, db):
    timer = TimerWindow(db, Hub())
    timer.updater = updater.Updater()  # как в main.py
    page = AboutPage(timer)
    texts = " ".join(label.text() for label in page.findChildren(QLabel))
    assert "MIT" in texts and about_page.REPO_URL in texts and "LGPL" in texts
    assert "никуда не отправляются" in texts
    link = next(l for l in page.findChildren(QLabel) if about_page.REPO_URL in l.text())
    assert link.openExternalLinks()
    timer.close()


def test_license_file_exists():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "LICENSE"), encoding="utf-8") as f:
        text = f.read()
    # Только текст MIT: с приписками GitHub не распознаёт лицензию (значок в README — NOASSERTION).
    assert text.startswith("MIT License") and text.rstrip().endswith("SOFTWARE.")
    with open(os.path.join(root, "THIRD_PARTY_NOTICES.md"), encoding="utf-8") as f:
        assert "LGPL" in f.read()
