"""Tray icon: shows whether the timer runs, pause/continue without opening the window."""
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import db as dbm
from . import theme

APP_TITLE = "Time Tracker"


def _icon(running):
    """App icon; while the timer runs, with a green dot in the corner."""
    base = theme.app_icon()
    if not running:
        return base
    pix = base.pixmap(64, 64)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(theme.BG), 4))
    p.setBrush(QColor(theme.ACTIVE))
    p.drawEllipse(QRectF(36, 36, 26, 26))
    p.end()
    return QIcon(pix)


class Tray(QSystemTrayIcon):
    def __init__(self, timer, hub):
        super().__init__(_icon(False))
        self.timer = timer
        self._running = None
        self._hint_shown = False
        self.menu = QMenu()
        self.menu.aboutToShow.connect(self._build_menu)
        self.setContextMenu(self.menu)
        self.activated.connect(self._on_activated)
        hub.changed.connect(self.update_state)
        self._clock = QTimer(self, interval=1000, timeout=self.update_state)
        self._clock.start()
        self.update_state()
        self.show()

    def update_state(self):
        active = self.timer._active()
        running = active is not None
        if running != self._running:
            self._running = running
            self.setIcon(_icon(running))
        if active:
            self.setToolTip(f"{APP_TITLE} — идёт {dbm.fmt_duration(active['total'])}\n"
                            f"{active['product']} · {active['subtask']}")
        else:
            self.setToolTip(f"{APP_TITLE} — таймер не запущен")

    def _on_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.timer.isVisible() and not self.timer.isMinimized():
                self.timer.hide()  # tray click hides everything; the compact widget is for minimize
            else:
                self.show_timer()

    def show_timer(self):
        self.timer.showNormal()
        self.timer.raise_()
        self.timer.activateWindow()

    def notify_hidden(self):
        """One-time hint after the first minimize to tray."""
        if not self._hint_shown:
            self._hint_shown = True
            self.showMessage(APP_TITLE, "Таймер спрятан в трей и продолжает работать. Клик по значку — открыть.",
                             self.icon(), 4000)

    def _build_menu(self):
        menu = self.menu
        menu.clear()
        timer = self.timer
        active = timer._active()
        if active:
            menu.addAction(theme.glyph_icon(theme.G_PAUSE), f"Пауза — {active['product']} · {active['subtask']}",
                           timer.pause)
        else:
            mode, target = timer._intent()
            product = timer.product.currentText().strip()
            subtask = timer.subtask.currentText().strip() or dbm.DEFAULT_SUBTASK
            if mode == "empty":
                menu.addAction(theme.glyph_icon(theme.G_PLAY), "Нет задачи — откройте таймер", self.show_timer)
            else:
                verb = {"resume": "Продолжить", "restart": "Возобновить"}.get(mode, "Начать")
                menu.addAction(theme.glyph_icon(theme.G_PLAY), f"{verb} — {product} · {subtask}", timer.play)
        stop = timer._stop_target()
        finish = menu.addAction(theme.glyph_icon(theme.G_STOP),
                                f"Завершить — {stop['product']} · {stop['subtask']}" if stop else "Завершить",
                                lambda: timer.stop())
        finish.setEnabled(stop is not None)
        menu.addSeparator()
        menu.addAction(theme.glyph_icon(theme.G_CLOCK), "Показать таймер", self.show_timer)
        menu.addAction(theme.glyph_icon(theme.G_CHART), "Журнал", lambda: timer.main_window.show_page(0))
        menu.addSeparator()
        menu.addAction(theme.glyph_icon(theme.G_CLOSE), "Выход", self._quit)

    def _quit(self):
        self.show_timer()  # closeEvent may ask to confirm pausing a running timer
        self.timer.close()
