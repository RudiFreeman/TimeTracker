"""Portable Time Tracker — entry point."""
import ctypes
import hashlib
import sqlite3
import sys
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from timetracker import dialogs, theme, update_dialog, updater
from timetracker.db import Database, app_dir
from timetracker.main_window import MainWindow
from timetracker.timer_window import APP_TITLE, Hub, TimerWindow
from timetracker.tray import Tray

_mutex = []  # keep the single-instance handle alive for the process lifetime


def _acquire_lock_file():
    """macOS / Linux: an exclusive lock on a file next to the database; the system drops it when
    the process exits, even after a crash."""
    import fcntl
    import os
    handle = open(os.path.join(app_dir(), ".timetracker.lock"), "w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return False
    _mutex.append(handle)
    return True


def acquire_single_instance():
    """One copy per folder: two copies on one database would run two timers at once."""
    if sys.platform != "win32":
        return _acquire_lock_file()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    name = "Local\\PortableTimeTracker-" + hashlib.md5(app_dir().casefold().encode("utf-8")).hexdigest()
    handle = kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        kernel32.CloseHandle(handle)
        return False
    _mutex.append(handle)
    return True


def wait_single_instance(seconds=15):
    """During an update the previous process is still closing for a moment — wait for its mutex."""
    deadline = time.monotonic() + seconds
    while not acquire_single_instance():
        if time.monotonic() > deadline:
            return False
        time.sleep(0.3)
    return True


def release_single_instance():
    if _mutex and sys.platform != "win32":
        _mutex.pop().close()
    elif _mutex:
        kernel32 = ctypes.WinDLL("kernel32")
        kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
        kernel32.CloseHandle(_mutex.pop())


def run_replacer(target):
    """TimeTracker.new.exe --replace <TimeTracker.exe>: no UI. Wait until the old app has exited,
    copy ourselves over it and start it (see timetracker/updater.py)."""
    ok = wait_single_instance(60) and updater.replace(target)
    release_single_instance()  # the started copy waits for it too
    updater.start(target, updater.UPDATED_FLAG if ok else updater.FAILED_FLAG)
    return 0


def main():
    if updater.REPLACE_FLAG in sys.argv[:-1]:
        return run_replacer(sys.argv[sys.argv.index(updater.REPLACE_FLAG) + 1])
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    theme.load_fonts()  # macOS: the bundled icon font
    # Windows' "slide open" combo animation leaves one frame with no list at all (the big timer
    # shows through) between the animation and the real popup.
    app.setEffectEnabled(Qt.UI_AnimateCombo, False)
    app.setStyle("Fusion")
    app.setPalette(theme.palette())
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(theme.app_icon())
    app.setQuitOnLastWindowClosed(False)  # the timer window decides when to quit

    after_update = updater.UPDATED_FLAG in sys.argv or updater.FAILED_FLAG in sys.argv
    got = wait_single_instance() if after_update else acquire_single_instance()
    if not got:
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

    updater.cleanup()  # .new.exe etc. left by the previous update

    hub = Hub()
    timer = TimerWindow(database, hub)
    timer.updater = updater.Updater()
    timer.main_window = MainWindow(database, hub, timer)
    if QSystemTrayIcon.isSystemTrayAvailable():
        timer.tray = Tray(timer, hub)
    timer.show()
    timer.daily_check = update_dialog.DailyCheck(timer)  # once a day from 09:00: offer a new version
    if updater.FAILED_FLAG in sys.argv:
        dialogs.notify(timer, "Обновление", "Не получилось установить новую версию: файл программы был занят. "
                       "Программа осталась прежней, данные на месте.\nПопробуйте ещё раз: «О программе» → «Обновить».")
    code = app.exec()
    database.close()
    if timer.restart_exe:  # the replacer takes over once this process has exited
        try:
            updater.launch_replacer(timer.restart_exe)
        except OSError:
            pass  # the user starts the program again; the next start removes .new.exe
    return code


if __name__ == "__main__":
    sys.exit(main())
