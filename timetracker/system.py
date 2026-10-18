"""OS integration. Start with the system (only for the built program):
Windows — HKCU Run key, macOS — a LaunchAgent in ~/Library/LaunchAgents. Open a folder in Explorer / Finder."""
import os
import plistlib
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "PortableTimeTracker"
AGENT_LABEL = "com.rudifreeman.timetracker"
AUTOSTART_TEXT = "Запускать вместе с macOS" if sys.platform == "darwin" else "Запускать вместе с Windows"


def autostart_supported():
    return sys.platform in ("win32", "darwin") and getattr(sys, "frozen", False)


def _command():
    return f'"{sys.executable}"'


def _agent_path():
    return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", AGENT_LABEL + ".plist")


def autostart_enabled():
    """True if the system starts *this* program (a stale entry for a moved copy doesn't count)."""
    if not autostart_supported():
        return False
    if sys.platform == "darwin":
        try:
            with open(_agent_path(), "rb") as f:
                return plistlib.load(f).get("ProgramArguments") == [sys.executable]
        except (OSError, ValueError):
            return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
    except OSError:
        return False
    return value.strip().casefold() == _command().casefold()


def set_autostart(enabled):
    if sys.platform == "darwin":
        path = _agent_path()
        if enabled:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                # AssociatedBundleIdentifiers: System Settings shows the app's name and icon for it
                # instead of an anonymous background item.
                plistlib.dump({"Label": AGENT_LABEL, "ProgramArguments": [sys.executable], "RunAtLoad": True,
                               "AssociatedBundleIdentifiers": [AGENT_LABEL]}, f)
        else:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass


def open_path(path):
    """Open a folder or file with the system (Explorer / Finder / the default app)."""
    if sys.platform == "win32":
        os.startfile(path)
    else:
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        QDesktopServices.openUrl(QUrl.fromLocalFile(path))
