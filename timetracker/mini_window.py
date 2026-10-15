"""Compact always-on-top widget shown while the timer window is minimized:
time, current task, the main pause/continue button, tokens and an expand button.
Drag anywhere to move; double click or ⤢ restores the full timer window."""
from PySide6.QtCore import QPoint, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import db as dbm
from . import theme


class HoverButton(QPushButton):
    """Icon button that lights up under the mouse, so it is obvious it can be clicked."""

    def __init__(self, glyph, tooltip):
        super().__init__(objectName="miniIcon", toolTip=tooltip)
        self._icons = (theme.glyph_icon(glyph, theme.TEXT_2), theme.glyph_icon(glyph, theme.ACCENT))
        self.setIcon(self._icons[0])
        self.setCursor(Qt.PointingHandCursor)

    def enterEvent(self, event):
        self.setIcon(self._icons[1])
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setIcon(self._icons[0])
        super().leaveEvent(event)


class MiniWindow(QWidget):
    def __init__(self, timer):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.timer = timer
        self.db = timer.db
        self._drag = None
        self._mode = None
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(322, 68)
        self._note = None  # short message shown instead of the task name for a few seconds
        self._note_timer = QTimer(self, singleShot=True, interval=4000, timeout=self._clear_note)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 6, 8, 6)
        layout.setSpacing(6)
        text = QVBoxLayout()
        text.setSpacing(0)
        self.time = QLabel("00:00:00", objectName="miniTime")
        self.task = QLabel(objectName="hint")
        self.task.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text.addWidget(self.time)
        text.addWidget(self.task)
        layout.addLayout(text, 1)

        self.main_btn = QPushButton(objectName="miniMain")
        self.main_btn.setFixedSize(36, 36)
        self.main_btn.setCursor(Qt.PointingHandCursor)
        self.main_btn.setIconSize(QSize(14, 14))
        self.main_btn.clicked.connect(timer._on_main)
        expand = HoverButton(theme.G_EXPAND, "Развернуть таймер (или двойной клик)")
        expand.setFixedSize(30, 30)
        expand.clicked.connect(self.expand)
        layout.addWidget(self.main_btn)
        tokens = HoverButton(theme.G_TOKENS, "Токены: записать расход на этот продукт")
        tokens.setFixedSize(30, 30)
        tokens.clicked.connect(self._add_tokens)
        layout.addWidget(tokens)
        layout.addWidget(expand)

    # ------------------------------------------------------------ state

    def sync(self):
        """Mirror the timer window: called from its refresh, every second."""
        if not self.isVisible():
            return
        active = self.timer._active()
        mode, target = self.timer._intent()
        shown = active or (target if mode == "resume" else None)
        self.time.setText(dbm.fmt_duration(shown["total"]) if shown else "00:00:00")
        running = "true" if active else "false"
        if self.time.property("running") != running:
            self.time.setProperty("running", running)
            self.time.style().unpolish(self.time)
            self.time.style().polish(self.time)
        if active:
            task = f"{active['product']} · {active['subtask']}"
        elif mode == "empty":
            task = "Нет задачи"
        else:
            product = self.timer.product.currentText().strip()
            subtask = self.timer.subtask.currentText().strip() or dbm.DEFAULT_SUBTASK
            # Paused is already clear from the grey digits and the play button.
            prefix = {"resume": "", "restart": "✓ "}.get(mode, "Новая: ")
            task = f"{prefix}{product} · {subtask}"
        self.setToolTip(task)
        if self._note:
            task = self._note
        self.task.setText(self.task.fontMetrics().elidedText(task, Qt.ElideRight, self.task.width() or 170))

        button = (self.timer.main_btn.text().strip(), self.timer.main_btn.property("mode"))
        if button != self._mode:
            self._mode = button
            label, style = button
            glyph = theme.G_PAUSE if style == "pause" else theme.G_PLAY
            self.main_btn.setIcon(theme.glyph_icon(glyph, "#000000"))
            self.main_btn.setToolTip(label)
            self.main_btn.setProperty("mode", style)
            self.main_btn.style().unpolish(self.main_btn)
            self.main_btn.style().polish(self.main_btn)
        self.main_btn.setEnabled(mode != "empty" or active is not None)

    def _add_tokens(self):
        note = self.timer.add_tokens(self)
        if note:
            self._note = note
            self._note_timer.start()
            self.sync()

    def _clear_note(self):
        self._note = None
        self.sync()

    def show_mini(self):
        self._restore_position()
        self.show()
        self.raise_()
        self.sync()

    def expand(self):
        self.hide()
        self.timer.showNormal()
        self.timer.raise_()
        self.timer.activateWindow()

    def hide_to_tray(self):
        self.hide()
        if self.timer.tray:
            self.timer.tray.notify_hidden()

    # ------------------------------------------------------------ position

    def _restore_position(self):
        try:
            x, y = (int(v) for v in self.db.get_setting("mini_position").split(","))
        except ValueError:
            # First time: where the timer window's top-left corner was.
            x, y = self.timer.x(), self.timer.y()
        screen = QGuiApplication.screenAt(QPoint(x + 20, y + 20)) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        x = min(max(x, area.left()), area.right() - self.width())
        y = min(max(y, area.top()), area.bottom() - self.height())
        self.move(x, y)

    # ------------------------------------------------------------ events

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(theme.BORDER), 1))
        p.setBrush(QColor(theme.CARD))
        p.drawRoundedRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5), 10, 10)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):
        if self._drag is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):
        if self._drag is not None:
            self._drag = None
            self.db.set_setting("mini_position", f"{self.x()},{self.y()}")

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.expand()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        menu.addAction(theme.glyph_icon(theme.G_EXPAND), "Развернуть", self.expand)
        if self.timer.tray:
            menu.addAction("Спрятать в трей", self.hide_to_tray)
        menu.exec(event.globalPos())
