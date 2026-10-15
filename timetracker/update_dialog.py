"""Окно «Доступно обновление» (что нового, скачивание с прогрессом) и `DailyCheck` — ежедневная
автопроверка + перезапуск в новую версию, когда она скачана.
The dialog never refuses to close: QApplication.quit() closes every window and is cancelled if one
ignores the close (the app would hang hidden). Closing it mid-download is fine — the download goes
on and DailyCheck restarts the app when it is ready."""
import sqlite3
from datetime import datetime, time, timedelta

from PySide6.QtCore import QObject, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton, QTextBrowser, QVBoxLayout,
)

from . import __version__, updater
from .theme import dark_title_bar

CHECK_AT = time(9, 0)                 # daily check from this time (or at start if later)
RETRY = timedelta(minutes=30)         # after a failed check (no network)
SKIP_KEY, CHECKED_KEY = "update_skip", "update_checked"  # settings: skipped version, date of last check


def finish_update(timer, new_exe):
    """Pause the timer, hand the new exe to main.py (it starts the replacer after quitting), quit.
    An open modal dialog (journal edit, a question) is never cut off: wait until it is closed."""
    if QApplication.activeModalWidget():
        QTimer.singleShot(1000, lambda: finish_update(timer, new_exe))
        return
    timer.db.pause_active()
    timer.hub.changed.emit()
    timer.restart_exe = new_exe
    timer.close()


class UpdateDialog(QDialog):
    """auto=True — offered by the daily check: «Пропустить» = don't offer this version again."""

    def __init__(self, parent, timer, release, auto=False):
        super().__init__(parent)
        self.timer = timer
        self.release = release
        self.auto = auto
        self.updater = timer.updater
        self._done = False
        self.setWindowTitle("Доступно обновление")
        self.setMinimumSize(460, 380)
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 14)
        root.setSpacing(10)

        root.addWidget(QLabel(f"Вышла версия {release.label}", objectName="title"))
        root.addWidget(QLabel(f"У вас {__version__}. Ваши данные сохранятся: обновляется только сама программа, "
                              "перед обновлением делается копия базы.", objectName="secondary", wordWrap=True))
        root.addWidget(QLabel("Что нового", objectName="section"))
        notes = QTextBrowser(objectName="plain", openExternalLinks=True)
        notes.setMarkdown(release.notes.replace("### ", "#### ") or "Описание не указано.")
        notes.document().setDocumentMargin(10)
        root.addWidget(notes, 1)

        self.bar = QProgressBar(textVisible=False, maximumHeight=6, visible=False)
        root.addWidget(self.bar)
        self.status = QLabel(objectName="hint", wordWrap=True, visible=False)
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.later = QPushButton("Пропустить" if auto else "Позже")
        self.later.setToolTip("Не напоминать об этой версии. Обновиться можно в любой момент "
                              "в «О программе»." if auto else "")
        self.later.clicked.connect(self._skip)
        self.ok = QPushButton("Обновить", objectName="accent", default=True)
        self.ok.clicked.connect(self._start)
        buttons.addWidget(self.later)
        buttons.addWidget(self.ok)
        root.addLayout(buttons)

        self.updater.progress.connect(self._on_progress)
        self.updater.prepared.connect(self._on_prepared)
        if self.updater.downloading:  # reopened from «О программе» while downloading
            self._downloading()
        elif not updater.can_install():
            self._say("Программа запущена не из своей папки с правом записи, поэтому обновить её "
                      "автоматически нельзя. «Обновить» откроет страницу, откуда можно скачать архив.")
        self.winId()
        dark_title_bar(self)

    def _say(self, text):
        self.status.setText(text)
        self.status.setVisible(bool(text))

    def _skip(self):
        if self.auto and self.later.text() == "Пропустить":
            self.timer.db.set_setting(SKIP_KEY, self.release.label)
        self.reject()

    def _start(self):
        if not updater.can_install():
            QDesktopServices.openUrl(QUrl(self.release.page))
            self.accept()
            return
        if not self.updater.backed_up:  # not on every retry: copies count toward BACKUP_KEEP
            try:
                self.timer.db.backup(force=True)
                self.updater.backed_up = True
            except (OSError, sqlite3.Error):
                pass  # the daily copy from today's start still exists
        self._downloading()
        self.updater.install(self.release)

    def _downloading(self):
        self.ok.setEnabled(False)
        self.later.setText("Скрыть")
        self.later.setToolTip("Скачивание продолжится, программа перезапустится сама.")
        self.bar.setVisible(True)
        self.bar.setRange(0, 0)
        self._say("Скачиваю…")

    def _on_progress(self, done, total):
        if total:
            self.bar.setRange(0, 1000)
            self.bar.setValue(int(done * 1000 / total))
            self._say(f"Скачиваю… {done / 1048576:.1f} из {total / 1048576:.1f} МБ")

    def _on_prepared(self, new_exe, error):
        """UI only — the restart itself is DailyCheck._on_prepared."""
        if new_exe:
            self.bar.setRange(0, 1000)
            self.bar.setValue(1000)
            self.later.setEnabled(False)
            self._say("Готово. Программа перезапустится" +
                      (", когда вы закроете открытое окно." if QApplication.activeModalWidget() else "…"))
            return
        self.bar.setVisible(False)
        self.later.setText("Закрыть")
        self.later.setToolTip("")
        self.ok.setEnabled(True)
        self.ok.clicked.disconnect()
        self.ok.clicked.connect(lambda: (QDesktopServices.openUrl(QUrl(self.release.page)), self.accept()))
        self._say(f"Не получилось обновить: {error}. Программа осталась прежней. "
                  "«Обновить» откроет страницу, откуда можно скачать архив.")

    def done(self, result):
        if not self._done:  # done() may come twice (button + close)
            self._done = True
            self.updater.progress.disconnect(self._on_progress)
            self.updater.prepared.disconnect(self._on_prepared)
        super().done(result)


def offer(parent, timer, release, auto=False):
    """Non-modal: the timer keeps ticking while the dialog is open. One dialog at a time — an
    existing one (even hidden with its owner window, e.g. mid-download) is shown again."""
    dlg = getattr(timer, "update_dialog", None)
    if dlg is None:
        dlg = UpdateDialog(parent, timer, release, auto)
        dlg.setModal(False)
        dlg.setAttribute(Qt.WA_DeleteOnClose)
        dlg.destroyed.connect(lambda: setattr(timer, "update_dialog", None))
        timer.update_dialog = dlg
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()
    return dlg


class DailyCheck(QObject):
    """Once a day from CHECK_AT (at start if the app is opened later): ask GitHub and offer a
    new version unless the user skipped exactly that one. A failed check retries in RETRY."""

    def __init__(self, timer):
        super().__init__(timer)
        self.timer = timer
        self.db = timer.db
        self._waiting = False  # our own request is in flight (the About button may check too)
        self._last_try = None
        self._checked = self.db.get_setting(CHECKED_KEY)  # date of the last successful check
        timer.updater.checked.connect(self._on_checked)
        timer.updater.prepared.connect(self._on_prepared)
        self._clock = QTimer(self, interval=60_000, timeout=self.maybe_check)
        self._clock.start()
        QTimer.singleShot(3000, self.maybe_check)  # let the window appear first
        # the replacer (.new.exe) may have still been closing at start; never touch a running download
        QTimer.singleShot(20000, lambda: updater.cleanup(downloads=not timer.updater.downloading))

    def maybe_check(self, at=None):
        at = at or datetime.now()
        if self._checked == at.date().isoformat() or at.time() < CHECK_AT:
            return
        if self.timer.updater.busy or self.timer.restart_exe:
            return
        if self._last_try and at - self._last_try < RETRY:
            return
        self._last_try = at
        self._waiting = True
        self.timer.updater.check()

    def _on_checked(self, release, error):
        if not self._waiting:
            return
        self._waiting = False
        if error or not release:
            return
        self._checked = datetime.now().date().isoformat()
        self.db.set_setting(CHECKED_KEY, self._checked)
        if release.is_newer() and self.db.get_setting(SKIP_KEY) != release.label:
            offer(self.timer, self.timer, release, auto=True)

    def _on_prepared(self, new_exe, _error):
        if new_exe:  # whether the dialog is still open or not
            finish_update(self.timer, new_exe)
