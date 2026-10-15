"""Portable Time Tracker — entry point."""
import ctypes
import hashlib
import sqlite3
import sys

from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from timetracker import dialogs, theme
from timetracker.db import Database, app_dir
from timetracker.main_window import MainWindow
from timetracker.timer_window import APP_TITLE, Hub, TimerWindow
from timetracker.tray import Tray

_mutex = []  # keep the single-instance handle alive for the process lifetime


def acquire_single_instance():
    """One copy per folder: two copies on one database would run two timers at once."""
    if sys.platform != "win32":
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    name = "Local\\PortableTimeTracker-" + hashlib.md5(app_dir().casefold().encode("utf-8")).hexdigest()
    handle = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return False
    _mutex.append(handle)
    return True


def main():
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(theme.app_icon())
    app.setQuitOnLastWindowClosed(False)  # the timer window decides when to quit

    if not acquire_single_instance():
        dialogs.error(None, APP_TITLE, "Программа уже запущена.")
        return 0
    try:
        database = Database()
    except sqlite3.Error as exc:
        dialogs.error(None, APP_TITLE, f"Не удалось открыть базу данных рядом с программой:\n{exc}")
        return 1
    try:
        database.backup()  # daily copy; a failure must not stop the app
    except (OSError, sqlite3.Error):
        pass

    hub = Hub()
    timer = TimerWindow(database, hub)
    timer.main_window = MainWindow(database, hub, timer)
    if QSystemTrayIcon.isSystemTrayAvailable():
        timer.tray = Tray(timer, hub)
    timer.show()
    code = app.exec()
    database.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
