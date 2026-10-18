"""Dark Windows 11-style theme: palette, stylesheet, glyph icons, formatting helpers."""
import ctypes
import os
import sys
import tempfile
import zlib

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap

# ----------------------------------------------------------------- palette
BG = "#202020"          # window background
SIDEBAR = "#1c1c1c"
CARD = "#2b2b2b"        # day headers, inputs
CARD_HOVER = "#323232"
ROW = "#262626"         # entry rows
ROW_HOVER = "#2e2e2e"
BORDER = "#383838"
TEXT = "#ffffff"
TEXT_2 = "#c8c8c8"      # secondary
TEXT_3 = "#8f8f8f"      # tertiary / hints
ACCENT = "#4cc2ff"
ACCENT_HOVER = "#47b1e8"
ACTIVE = "#6ccb5f"      # running timer
WARN = "#ff99a4"
PAUSE = "#ffc83d"       # main timer button while a task is running
PAUSE_HOVER = "#f0b929"
TRACK = "#2e2e2e"       # empty timeline track
TRACK_WORK = "#4a4a4a"  # working hours on the timeline track

PRODUCT_COLORS = ["#c5b31c", "#6ccb5f", "#f7630c", "#4c8bf5", "#b46ef0", "#2ec7b5", "#ef6ea8", "#e8a33a"]

MAC = sys.platform == "darwin"
# A point is smaller on macOS (72 dpi vs 96 on Windows): every font size goes through pt() so the
# layout looks the same on both.
PT_SCALE = 4 / 3 if MAC else 1.0


def pt(size):
    """Font size in Windows points -> the same visual size on this system."""
    return round(size * PT_SCALE, 2) if MAC else size


if MAC:
    # Segoe MDL2 Assets exists only on Windows. The same icons from Microsoft's Fluent UI System Icons
    # (MIT), cut down to these glyphs: timetracker/icons.ttf, registered by load_fonts().
    ICON_FONT = "FluentSystemIcons-Regular"
    GLYPH_SCALE = 1.0  # Fluent glyphs have less padding than MDL2
    G_PLAY, G_PAUSE, G_STOP = "", "", ""
    G_ADD, G_CHECK, G_CLOSE = "", "", ""
    G_DOWN, G_UP, G_RIGHT = "", "", ""
    G_CLOCK, G_CHART, G_SETTINGS = "", "", ""
    G_PIN, G_PINNED, G_EXPORT, G_DELETE, G_SEARCH = "", "", "", "", ""
    G_EDIT = ""
    G_EXPAND = ""
    G_TOKENS = ""
    G_INFO = ""
    UI_FONT = DISPLAY_FONT = ""  # the system font
else:
    ICON_FONT = "Segoe MDL2 Assets"
    GLYPH_SCALE = 0.8
    G_PLAY, G_PAUSE, G_STOP = "", "", ""
    G_ADD, G_CHECK, G_CLOSE = "", "", ""
    G_DOWN, G_UP, G_RIGHT = "", "", ""
    G_CLOCK, G_CHART, G_SETTINGS = "", "", ""
    G_PIN, G_PINNED, G_EXPORT, G_DELETE, G_SEARCH = "", "", "", "", ""
    G_EDIT = ""  # Edit (pencil)
    G_EXPAND = ""  # FullScreen arrows
    G_TOKENS = ""  # Calculator
    G_INFO = ""  # Info
    UI_FONT = '"Segoe UI Variable Text", "Segoe UI"'
    DISPLAY_FONT = '"Segoe UI Variable Display", "Segoe UI"'


def load_fonts():
    """Register the bundled icon font (macOS). Call once, after QApplication is created."""
    if MAC:
        from PySide6.QtGui import QFontDatabase
        QFontDatabase.addApplicationFont(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons.ttf"))


WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def product_color(product_id):
    """Stable color per product."""
    return PRODUCT_COLORS[zlib.crc32(str(product_id).encode()) % len(PRODUCT_COLORS)]


def fmt_human(seconds):
    """1 ч 26 мин / 2 мин / 35 сек."""
    seconds = int(max(0, round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes = rest // 60
    if hours and minutes:
        return f"{hours} ч {minutes} мин"
    if hours:
        return f"{hours} ч"
    if minutes:
        return f"{minutes} мин"
    return f"{seconds} сек"


def fmt_tokens(count):
    """1234567 -> '1 234 567' (non-breaking spaces)."""
    return f"{int(count):,}".replace(",", " ")


def fmt_day(day):
    return f"{WEEKDAYS[day.weekday()]}, {day:%d.%m.%Y}"


# ------------------------------------------------------------------- icons

def glyph_pixmap(glyph, color=TEXT, size=16):
    ratio = 2  # render at 2x so icons stay crisp on scaled displays
    pix = QPixmap(size * ratio, size * ratio)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.TextAntialiasing)
    font = QFont(ICON_FONT)
    font.setPixelSize(int(size * ratio * GLYPH_SCALE))
    p.setFont(font)
    p.setPen(QColor(color))
    p.drawText(QRect(0, 0, size * ratio, size * ratio), Qt.AlignCenter, glyph)
    p.end()
    pix.setDevicePixelRatio(ratio)
    return pix


def glyph_icon(glyph, color=TEXT, size=16, disabled=TEXT_3):
    icon = QIcon(glyph_pixmap(glyph, color, size))
    icon.addPixmap(glyph_pixmap(glyph, disabled, size), QIcon.Disabled)
    return icon


def app_icon():
    """Application icon (timetracker/icon.png, bundled into the exe); clock glyph if it is missing."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.png")
    return QIcon(path) if os.path.exists(path) else glyph_icon(G_CLOCK, ACCENT, 32)


def dot_icon(color, size=10):
    pix = QPixmap(size * 2, size * 2)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    p.drawEllipse(2, 2, size * 2 - 4, size * 2 - 4)
    p.end()
    pix.setDevicePixelRatio(2)
    return QIcon(pix)


def _asset_dir():
    """PNG glyphs referenced from the stylesheet (QSS needs files)."""
    folder = os.path.join(tempfile.gettempdir(), "portable_time_tracker_assets")
    os.makedirs(folder, exist_ok=True)
    for name, glyph, color, size in (
        ("down", G_DOWN, TEXT_2, 10), ("up", G_UP, TEXT_2, 10), ("right", G_RIGHT, TEXT_2, 10),
        ("check", G_CHECK, "#000000", 12),
    ):
        glyph_pixmap(glyph, color, size).save(os.path.join(folder, f"{name}.png"))
    return folder.replace("\\", "/")


def stylesheet():
    a = _asset_dir()
    ui = f"font-family: {UI_FONT}; " if UI_FONT else ""
    display = f"font-family: {DISPLAY_FONT}; " if DISPLAY_FONT else ""
    return f"""
* {{ {ui}font-size: {pt(10)}pt; color: {TEXT}; }}
QWidget#window, QDialog, QMessageBox {{ background: {BG}; }}
QWidget#sidebar {{ background: {SIDEBAR}; }}
QLabel#title {{ font-size: {pt(18)}pt; font-weight: 600; }}
QLabel#hint {{ color: {TEXT_3}; font-size: {pt(9)}pt; }}
QLabel#secondary {{ color: {TEXT_2}; }}
QLabel#section {{ font-weight: 600; font-size: {pt(10.5)}pt; }}
QLabel#timer {{ {display}font-size: {pt(30)}pt; font-weight: 600; color: {TEXT_3}; }}
QLabel#timer[running="true"] {{ color: {ACTIVE}; }}
QFrame#card {{ background: {CARD}; border-radius: 6px; }}

QLineEdit, QComboBox, QTimeEdit, QDateEdit {{
    background: {CARD}; border: 1px solid {BORDER}; border-bottom: 1px solid #6b6b6b;
    border-radius: 4px; padding: 4px 8px; min-height: 20px; selection-background-color: #0078d4;
}}
QLineEdit:hover, QComboBox:hover, QTimeEdit:hover, QDateEdit:hover {{ background: {CARD_HOVER}; }}
QLineEdit:focus, QComboBox:focus, QTimeEdit:focus, QDateEdit:focus {{ background: #1f1f1f; border-bottom: 2px solid {ACCENT}; }}
QComboBox#pick {{ background: {ROW}; border: 1px solid {BORDER}; color: {TEXT_2}; combobox-popup: 0; }}
QComboBox#pick:hover {{ background: {CARD}; }}
QComboBox::drop-down {{ border: none; width: 26px; }}
QComboBox::down-arrow {{ image: url({a}/down.png); width: 10px; height: 10px; }}
QComboBox QAbstractItemView, QListView#completer {{
    background: #2c2c2c; border: 1px solid #3d3d3d; outline: none; padding: 2px;
    selection-background-color: #3a3a3a;
}}
QComboBox QAbstractItemView::item {{ min-height: 24px; padding-left: 6px; }}
QTimeEdit::up-button, QTimeEdit::down-button {{ width: 0; border: none; }}
QDateEdit::drop-down {{ border: none; width: 22px; }}
QDateEdit::down-arrow {{ image: url({a}/down.png); width: 10px; height: 10px; }}

QPushButton {{
    background: {CARD}; border: 1px solid {BORDER}; border-radius: 4px; padding: 5px 12px; min-height: 20px;
}}
QPushButton:hover {{ background: {CARD_HOVER}; }}
QPushButton:pressed {{ background: #262626; color: {TEXT_2}; }}
QPushButton:disabled {{ color: {TEXT_3}; }}
QPushButton#accent {{ background: {ACCENT}; color: #000000; border: none; font-weight: 600; }}
QPushButton#accent:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#accent:pressed {{ background: #42a1d2; }}
QPushButton#main {{ background: {ACCENT}; color: #000000; border: none; font-weight: 600; font-size: {pt(10.5)}pt; }}
QPushButton#main:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#main[mode="pause"] {{ background: {PAUSE}; }}
QPushButton#main[mode="pause"]:hover {{ background: {PAUSE_HOVER}; }}
QLabel#miniTime {{ {display}font-size: {pt(20)}pt; font-weight: 600; color: {TEXT_3}; }}
QLabel#miniTime[running="true"] {{ color: {ACTIVE}; }}
QPushButton#miniMain {{ background: {ACCENT}; border: none; border-radius: 18px; padding: 0; min-height: 0; }}
QPushButton#miniIcon {{ background: transparent; border: none; border-radius: 6px; padding: 0; min-height: 0; }}
QPushButton#miniIcon:hover {{ background: #3d3d3d; }}
QPushButton#miniIcon:pressed {{ background: #474747; }}
QPushButton#miniMain:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#miniMain[mode="pause"] {{ background: {PAUSE}; }}
QPushButton#miniMain[mode="pause"]:hover {{ background: {PAUSE_HOVER}; }}
QPushButton#miniMain:disabled {{ background: {CARD_HOVER}; }}
QPushButton#flat {{ background: transparent; border: none; padding: 5px 8px; }}
QPushButton#flat:hover {{ background: {CARD}; }}
QPushButton#flat:checked {{ background: {CARD}; color: {ACCENT}; }}

QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid #8a8a8a; background: #272727; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; image: url({a}/check.png); }}

QListWidget#nav {{ background: transparent; border: none; outline: none; }}
QListWidget#nav::item {{ height: 36px; padding-left: 8px; border-radius: 4px; margin: 1px 6px; color: {TEXT}; }}
QListWidget#nav::item:hover {{ background: #2a2a2a; }}
QListWidget#nav::item:selected {{ background: #2d2d2d; color: {TEXT}; border-left: 3px solid {ACCENT}; }}

QTreeView, QListView {{ background: transparent; border: none; outline: none; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QTreeWidget#summary::item:hover {{ background: {ROW_HOVER}; }}
QTreeWidget#summary::item:selected {{ background: #333333; color: {TEXT}; }}
QTreeWidget#summary::branch {{ background: transparent; }}
QTreeWidget#summary::branch:selected {{ background: #333333; }}
QTreeWidget#summary::branch:has-children:closed, QTreeWidget#summary::branch:has-children:open {{ image: none; }}
QListWidget#plain {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 6px; padding: 4px; }}
QListWidget#plain::item {{ height: 26px; padding-left: 6px; border-radius: 4px; }}
QListWidget#plain::item:selected {{ background: #3a3a3a; color: {TEXT}; }}
QHeaderView::section {{ background: {BG}; color: {TEXT_3}; border: none; padding: 4px 8px; font-size: {pt(9)}pt; }}

QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #5c5c5c; border-radius: 3px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #7a7a7a; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QScrollBar:horizontal {{ height: 0; }}

QMenu {{ background: #2c2c2c; border: 1px solid #3d3d3d; border-radius: 6px; padding: 4px; }}
QMenu::item {{ padding: 6px 24px 6px 12px; border-radius: 4px; }}
QMenu::item:selected {{ background: #383838; }}
QMenu::separator {{ height: 1px; background: #3d3d3d; margin: 4px 6px; }}
QToolTip {{ background: #2c2c2c; color: {TEXT}; border: 1px solid #3d3d3d; padding: 4px; }}
QMessageBox QPushButton {{ min-width: 80px; }}
"""


def palette():
    """Dark palette for the Fusion style, so widgets the stylesheet doesn't cover stay dark."""
    pal = QPalette()
    for role, color in (
        (QPalette.Window, BG), (QPalette.WindowText, TEXT), (QPalette.Base, CARD), (QPalette.AlternateBase, ROW),
        (QPalette.Text, TEXT), (QPalette.Button, CARD), (QPalette.ButtonText, TEXT), (QPalette.ToolTipBase, "#2c2c2c"),
        (QPalette.ToolTipText, TEXT), (QPalette.Highlight, "#0078d4"), (QPalette.HighlightedText, TEXT),
        (QPalette.PlaceholderText, TEXT_3), (QPalette.Link, ACCENT),
    ):
        pal.setColor(role, QColor(color))
    for role in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor(TEXT_3))
    return pal


def show_on_all_spaces(widget):
    """macOS: keep the window on every desktop (Space) and over full-screen apps. Call after show():
    the native NSWindow exists only then. Qt has no API for it, so NSWindow.setCollectionBehavior via
    the Objective-C runtime (no PyObjC in the build)."""
    if not MAC:
        return
    try:
        import ctypes.util
        objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
        objc.sel_registerName.restype = ctypes.c_void_p
        objc.sel_registerName.argtypes = (ctypes.c_char_p,)
        send = ctypes.cast(objc.objc_msgSend, ctypes.c_void_p).value
        get = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(send)
        put = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)(send)
        window = get(int(widget.winId()), objc.sel_registerName(b"window"))  # winId() is the NSView
        if window:
            can_join_all_spaces, full_screen_auxiliary = 1 << 0, 1 << 8
            put(window, objc.sel_registerName(b"setCollectionBehavior:"), can_join_all_spaces | full_screen_auxiliary)
    except (AttributeError, OSError, TypeError):
        pass


def dark_title_bar(widget):
    """Ask Windows 10 (1809+) / 11 to draw a dark title bar for this window."""
    if sys.platform != "win32":
        return
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (new / pre-20H1 id)
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
    except (AttributeError, OSError):
        pass
