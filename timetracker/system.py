"""Windows integration: start with Windows (HKCU Run key). Only for the built exe."""
import sys

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "PortableTimeTracker"


def autostart_supported():
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def _command():
    return f'"{sys.executable}"'


def autostart_enabled():
    """True if Windows starts *this* exe (a stale entry for a moved copy doesn't count)."""
    if not autostart_supported():
        return False
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, RUN_NAME)
    except OSError:
        return False
    return value.strip().casefold() == _command().casefold()


def set_autostart(enabled):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
