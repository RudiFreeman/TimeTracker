"""Floating timer window: product/subtask fields, big timer, Start/Pause/Stop, open sessions."""
import sqlite3
from datetime import datetime

from PySide6.QtCore import QEvent, QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QComboBox, QCompleter, QGridLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QMenu, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)

from . import db as dbm
from . import dialogs, theme
from .delegates import DATA, Box, EntryDelegate, payload
from .mini_window import MiniWindow

APP_TITLE = "Time Tracker"
SLEEP_GAP = 300        # seconds without a tick => PC was asleep/locked; pause at the last tick
HEARTBEAT_EVERY = 15   # seconds between crash-recovery heartbeats


class Hub(QObject):
    """Data changed somewhere — every window refreshes."""
    changed = Signal()


class TimerWindow(QWidget):
    def __init__(self, database, hub):
        super().__init__()
        self.db = database
        self.hub = hub
        self.main_window = None  # set by main.py
        self.tray = None         # set by main.py when the system tray is available
        self.mini = None         # compact widget shown while minimized
        self.updater = None      # updater.Updater, set by main.py
        self.restart_exe = None  # new exe to start after quitting (update_dialog.finish_update)
        self._sessions = {}
        self._list_ids = []
        self._last_active_id = None
        self._just_completed = False
        self._last_tick = dbm.now()
        self._last_heartbeat = self._last_tick
        self._themed = False

        self.setObjectName("window")
        self.setWindowTitle(APP_TITLE)
        self.resize(380, 470)
        self.setMinimumWidth(340)
        self._build_ui()
        self._apply_topmost(self.db.get_setting("topmost") == "1", save=False)
        self._restore_position()

        self.hub.changed.connect(self.reload)
        self._status_timer = QTimer(self, singleShot=True, interval=10000, timeout=self.status.hide)
        if self.db.recover():
            self._flash("Таймер с прошлого запуска поставлен на паузу (программа закрылась некорректно).", warn=True)
        self.reload()
        self._restore_fields()
        self.mini = MiniWindow(self)
        self._ticker = QTimer(self, interval=1000, timeout=self._tick)
        self._ticker.start()

    # --------------------------------------------------------------------- UI

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 10)
        root.setSpacing(8)

        form = QGridLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(6)
        form.setColumnStretch(1, 1)
        self.product = self._make_combo("Название продукта")
        self.subtask = self._make_combo("Тип работы")
        add = QPushButton(objectName="flat", icon=theme.glyph_icon(theme.G_ADD), toolTip="Создать новую подзадачу")
        add.clicked.connect(self.create_subtask)
        for row, (text, widget) in enumerate((("Продукт", self.product), ("Подзадача", self.subtask))):
            form.addWidget(QLabel(text, objectName="secondary"), row, 0)
            form.addWidget(widget, row, 1)
        form.addWidget(add, 1, 2)
        new_product = QPushButton(objectName="flat", icon=theme.glyph_icon(theme.G_ADD), toolTip="Новый продукт")
        new_product.clicked.connect(self.new_product)
        form.addWidget(new_product, 0, 2)
        root.addLayout(form)

        self.timer_label = QLabel("00:00:00", objectName="timer", alignment=Qt.AlignCenter)
        tokens = QPushButton(objectName="flat", icon=theme.glyph_icon(theme.G_TOKENS, size=22),
                             toolTip="Токены: записать расход (ElevenLabs и т.п.) на этот продукт")
        tokens.setIconSize(QSize(22, 22))
        tokens.setFixedSize(44, 44)
        tokens.clicked.connect(lambda: self.add_tokens())
        timer_row = QHBoxLayout()
        timer_row.addSpacing(44)
        timer_row.addWidget(self.timer_label, 1)
        timer_row.addWidget(tokens, 0, Qt.AlignVCenter)
        root.addLayout(timer_row)
        self.current = QLabel(objectName="secondary", alignment=Qt.AlignCenter)
        self.current.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        root.addWidget(self.current)

        # One main button that always shows the single thing a click will do (see _intent),
        # plus "Завершить", which closes a session for good.
        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.main_btn = QPushButton(objectName="main")
        self.main_btn.clicked.connect(self._on_main)
        self.stop_btn = QPushButton(" Завершить", icon=theme.glyph_icon(theme.G_STOP))
        self.stop_btn.clicked.connect(self._on_second)
        self._second = None
        for button in (self.main_btn, self.stop_btn):
            button.setMinimumHeight(34)
        buttons.addWidget(self.main_btn, 1)
        buttons.addWidget(self.stop_btn)
        root.addLayout(buttons)
        self.hint = QLabel(objectName="hint", alignment=Qt.AlignCenter, wordWrap=True)
        self.hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        root.addWidget(self.hint)
        self._mode = None

        self.list_title = QLabel(objectName="hint")
        root.addSpacing(4)
        root.addWidget(self.list_title)
        self.list = QListWidget()
        self.list.setItemDelegate(EntryDelegate(self.list))
        self.list.setMouseTracking(True)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.itemClicked.connect(self._on_item_clicked)
        self.list.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.list.itemSelectionChanged.connect(self._update_timer)
        self.list.customContextMenuRequested.connect(self._list_menu)
        root.addWidget(self.list, 1)

        footer = QHBoxLayout()
        footer.setSpacing(2)
        self.today = QLabel(objectName="secondary")
        footer.addWidget(self.today)
        footer.addStretch(1)
        self.pin_btn = QPushButton(objectName="flat", checkable=True, toolTip="Поверх всех окон")
        self.pin_btn.toggled.connect(self._apply_topmost)
        journal = QPushButton(" Журнал", objectName="flat", icon=theme.glyph_icon(theme.G_CLOCK))
        journal.clicked.connect(lambda: self.main_window.show_page(0))
        settings = QPushButton(objectName="flat", icon=theme.glyph_icon(theme.G_SETTINGS), toolTip="Настройки")
        settings.clicked.connect(lambda: self.main_window.show_page(2))
        for button in (self.pin_btn, journal, settings):
            footer.addWidget(button)
        root.addLayout(footer)

        # Short messages under the footer; hidden when empty so it doesn't leave a blank strip.
        self.status = QLabel(objectName="hint", wordWrap=True, visible=False)
        root.addWidget(self.status)

    def _make_combo(self, placeholder):
        combo = QComboBox(editable=True, insertPolicy=QComboBox.NoInsert, maxVisibleItems=12)
        combo.lineEdit().setPlaceholderText(placeholder)
        completer = QCompleter(combo.model(), combo)
        completer.setFilterMode(Qt.MatchContains)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setCompletionMode(QCompleter.PopupCompletion)
        completer.popup().setObjectName("completer")
        completer.activated.connect(self._mark_completed)
        combo.setCompleter(completer)
        combo.lineEdit().returnPressed.connect(self._on_return)
        combo.editTextChanged.connect(lambda _: self._update_timer())  # main button follows the fields
        return combo

    def _mark_completed(self, *_):
        # Enter that picks a suggestion must not also start the timer.
        self._just_completed = True
        QTimer.singleShot(0, lambda: setattr(self, "_just_completed", False))

    def _on_return(self):
        if not self._just_completed:
            self.play()

    @staticmethod
    def _fill(combo, names):
        text = combo.currentText()
        combo.blockSignals(True)
        combo.clear()
        combo.addItems(names)
        combo.setEditText(text)
        combo.blockSignals(False)

    @staticmethod
    def _set_text(combo, text):
        combo.setEditText(text)

    # ---------------------------------------------------------------- actions

    def play(self):
        product = self.product.currentText().strip()
        subtask = self.subtask.currentText().strip() or dbm.DEFAULT_SUBTASK
        if not product:
            self._flash("Введите название продукта.", warn=True)
            self.product.setFocus()
            return

        subtask_id = self.db.find_subtask(subtask)
        if subtask_id is None:
            if not dialogs.ask(self, "Новая подзадача", f"Подзадачи «{subtask}» нет в списке.\nСоздать её?"):
                return
            subtask_id = self.db.create_subtask(subtask)

        product_id = self.db.find_product(product)
        active = self.db.active_session()
        if active and active["product_id"] == product_id and active["subtask_id"] == subtask_id:
            self._flash("Эта задача уже идёт.")
            return
        after_hours = self._confirm_after_hours()
        if after_hours is None:
            return
        if product_id is None:
            product_id = self.db.get_or_create_product(product)
        session_id = self.db.start(product_id, subtask_id, after_hours)
        self._after_switch(session_id, active)

    def resume(self, session_id):
        active = self.db.active_session()
        if active and active["id"] == session_id:
            return
        after_hours = self._confirm_after_hours()
        if after_hours is None:
            return
        if self.db.resume(session_id, after_hours):
            self._after_switch(session_id, active)

    def continue_task(self, session_id, product_id, subtask_id, status):
        """Continue a journal entry: resume it if paused, otherwise open a new session for the same pair."""
        if status == "active":
            return
        if status == "paused":
            self.resume(session_id)
            return
        active = self.db.active_session()
        after_hours = self._confirm_after_hours()
        if after_hours is None:
            return
        new_id = self.db.start(product_id, subtask_id, after_hours)
        self._after_switch(new_id, active)

    def _after_switch(self, session_id, previous):
        self.hub.changed.emit()
        self._select(session_id)
        if previous:
            self._flash(f"На паузу: {previous['product']} · {previous['subtask']}")
        else:
            self._flash("Таймер запущен.")

    def pause(self):
        active = self.db.active_session()
        if not active:
            self._flash("Нет запущенного таймера.")
            return
        self.db.pause_active()
        self._flash(f"На паузе: {active['product']} · {active['subtask']}")
        self.hub.changed.emit()

    def stop(self, session_id=None):
        if session_id is None:
            target = self._stop_target()
            session_id = target["id"] if target else None
        if session_id is None:
            self._flash("Нечего завершать: запустите задачу или выберите её в списке.")
            return
        info = self._sessions.get(session_id)
        self.db.stop(session_id)
        if info:
            total = self.db.session_total(session_id)
            self._flash(f"Завершено: {info['product']} · {info['subtask']} — {theme.fmt_human(total)}")
        self.hub.changed.emit()

    def new_product(self):
        dlg = dialogs.NewProductDialog(self, self.db.product_names(include_archived=True), self.db.subtask_names(),
                                       self.subtask.currentText().strip() or dbm.DEFAULT_SUBTASK)
        if not dlg.exec():
            return
        name, subtask = dlg.values()
        self._set_text(self.product, name)
        self._set_text(self.subtask, subtask or dbm.DEFAULT_SUBTASK)
        if dlg.start:
            self.play()
            return
        if self.db.find_product(name) is None:
            self.db.get_or_create_product(name)
            self.hub.changed.emit()
            self._flash(f"Продукт «{name}» создан.")

    def create_subtask(self):
        name = dialogs.ask_text(self, "Новая подзадача", "Название подзадачи:")
        if not name:
            return
        self.db.create_subtask(name)
        self.hub.changed.emit()
        self.subtask.setEditText(name)
        self._flash(f"Подзадача «{name}» добавлена.")

    def add_tokens(self, parent=None):
        """Token dialog over `parent` (the mini window when minimized). Returns the result text or None."""
        parent = parent or self
        models = self.db.model_names()
        def history(name):
            product_id = self.db.find_product(name) if name else None
            return self.db.token_history(product_id) if product_id is not None else []

        def delete(usage_id):
            self.db.delete_tokens(usage_id)
            self.hub.changed.emit()

        dlg = dialogs.TokenDialog(parent, self.db.product_names(), self.product.currentText().strip(),
                                  models, models[0] if models else "", history, delete)
        if not dlg.exec():
            return
        product, model, tokens = dlg.values()
        product_id = self.db.find_product(product)
        if product_id is None:
            if not dialogs.ask(parent, "Новый продукт", f"Продукта «{product}» ещё нет.\nСоздать его?"):
                return None
            product_id = self.db.get_or_create_product(product)
        self.db.add_tokens(product_id, model, tokens)
        self.hub.changed.emit()
        self._flash(f"+{theme.fmt_tokens(tokens)} токенов ({model}) → {product}. "
                    f"Всего по продукту: {theme.fmt_tokens(self.db.product_tokens(product_id))}")
        return f"+{theme.fmt_tokens(tokens)} токенов → {product}"

    def _confirm_after_hours(self):
        """False if within working hours, True if the user agreed to work late, None if cancelled."""
        if not self.db.is_after_limit(dbm.now()):
            return False
        _, limit = self.db.limit_config()
        ok = dialogs.ask(
            self, "После окончания рабочего дня",
            f"Сейчас уже после {limit:%H:%M}.\nЗапустить таймер всё равно?\n\nОн автоматически остановится в 23:59.",
            warning=True,
        )
        return True if ok else None

    # ------------------------------------------------------------- open list

    def _selected_id(self):
        items = self.list.selectedItems()
        return payload(self.list.indexFromItem(items[0])).get("id") if items else None

    def _select(self, session_id):
        for row in range(self.list.count()):
            item = self.list.item(row)
            if payload(self.list.indexFromItem(item)).get("id") == session_id:
                self.list.setCurrentItem(item)
                return

    def _on_item_clicked(self, item):
        s = payload(self.list.indexFromItem(item))
        self._set_text(self.product, s["product"])
        if s.get("kind") != "group":
            self._set_text(self.subtask, s["subtask"])

    def _on_item_double_clicked(self, item):
        s = payload(self.list.indexFromItem(item))
        if s.get("kind") != "group":
            self._continue(s)

    def _list_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        s = payload(self.list.indexFromItem(item))
        menu = QMenu(self)
        if s.get("kind") == "group":
            pass  # product header: only the product actions below
        elif s["status"] == "active":
            menu.addAction(theme.glyph_icon(theme.G_PAUSE), "Пауза", self.pause)
        else:
            menu.addAction(theme.glyph_icon(theme.G_PLAY), "Возобновить" if s["status"] == "stopped" else "Продолжить",
                           lambda: self._continue(s))
        if s.get("status", "stopped") != "stopped":
            menu.addAction(theme.glyph_icon(theme.G_STOP), "Завершить сессию", lambda: self.stop(s["id"]))
        menu.addAction(theme.glyph_icon(theme.G_CHECK), "Сдать продукт",
                       lambda: self.archive_product(s["product_id"], s["product"]))
        menu.addSeparator()
        menu.addAction(theme.glyph_icon(theme.G_CHART), "Сводка по продукту",
                       lambda: self.main_window.show_product(1, s["product"]))
        menu.addAction(theme.glyph_icon(theme.G_CLOCK), "Журнал по продукту",
                       lambda: self.main_window.show_product(0, s["product"]))
        menu.exec(self.list.viewport().mapToGlobal(pos))

    def _continue(self, s):
        self.continue_task(s["id"], s["product_id"], s["subtask_id"], s["status"])

    def archive_product(self, product_id, name):
        """«Сдать»: the product leaves the list and suggestions (stays in Summary/Journal)."""
        if not dialogs.confirm_archive(self, name, self.db.open_session_count(product_id)):
            return
        self.db.set_archived(product_id, True)
        if self.product.currentText().strip().casefold() == name.casefold():
            self._set_text(self.product, "")
        self._flash(f"«{name}» сдан.")
        self.hub.changed.emit()

    # ------------------------------------------------------------- refresh

    def reload(self):
        """Lists of names may have changed (new product, renamed, subtask added)."""
        self._fill(self.product, self.db.product_names())
        self._fill(self.subtask, self.db.subtask_names())
        if not self.subtask.currentText():
            self.subtask.setEditText(dbm.DEFAULT_SUBTASK)
        self.refresh()

    def refresh(self):
        at = dbm.now()
        sessions = self.db.work_sessions(at)
        tokens = self.db.token_totals()
        for s in sessions:
            s["tokens"] = tokens.get(s["product_id"], 0)
        self._sessions = {s["id"]: s for s in sessions}

        rows = self._group_rows(sessions, tokens)
        ids = [row.get("id", ("group", row["product_id"])) for row in rows]
        if ids != self._list_ids:
            selected = self._selected_id()
            self.list.blockSignals(True)
            self.list.clear()
            for row in rows:
                item = QListWidgetItem()
                item.setData(DATA, Box(row))
                if row.get("kind") == "group":
                    item.setFlags(Qt.ItemIsEnabled)  # header: not selectable
                    item.setToolTip(row["product"])
                else:
                    item.setToolTip(f"{row['product']} · {row['subtask']}")
                self.list.addItem(item)
            self.list.blockSignals(False)
            self._list_ids = ids
            if selected in self._sessions:
                self._select(selected)
        else:
            for i, row in enumerate(rows):
                self.list.item(i).setData(DATA, Box(row))
        groups = len(rows) - len(sessions)
        self.list_title.setText(f"Продуктов: {groups}  ·  задач: {len(sessions)}  ·  двойной клик — продолжить"
                                if sessions else "Нет задач в работе")

        active = next((s for s in sessions if s["status"] == "active"), None)
        active_id = active["id"] if active else None
        if active and active_id != self._last_active_id:
            self._set_text(self.product, active["product"])
            self._set_text(self.subtask, active["subtask"])
        self._last_active_id = active_id

        today = datetime.combine(at.date(), datetime.min.time())
        self.today.setText(f"Сегодня: {theme.fmt_human(self.db.total_between(today, at, at))}")
        self._update_timer()

    @staticmethod
    def _group_rows(sessions, tokens):
        """List rows: a header per product, then its subtasks. Sessions come active first, then by
        last activity, so products keep that order (the running one on top) and so do subtasks."""
        groups = {}
        for s in sessions:
            groups.setdefault(s["product_id"], []).append(s)
        rows = []
        for product_id, items in groups.items():
            open_items = [s for s in items if s["status"] != "stopped"]
            rows.append({"kind": "group", "product_id": product_id, "product": items[0]["product"],
                         "tokens": tokens.get(product_id, 0), "first": not rows,
                         "active": any(s["status"] == "active" for s in items),
                         "total": sum(s["total"] for s in open_items) if open_items else None})
            rows.extend(items)
        return rows

    def _active(self):
        return next((s for s in self._sessions.values() if s["status"] == "active"), None)

    def _intent(self):
        """What the main button does for the product/subtask in the fields.

        Returns (mode, target): mode is 'pause' (that task is running), 'resume' (it is on
        pause), 'restart' (its last session is finished -> a new one), 'start' (nothing yet ->
        a new one) or 'empty' (no product typed); target is the matching listed session or None.
        """
        active = self._active()
        product = self.product.currentText().strip()
        if not product:
            return ("pause", active) if active else ("empty", None)
        product_id = self.db.find_product(product)
        subtask_id = self.db.find_subtask(self.subtask.currentText().strip() or dbm.DEFAULT_SUBTASK)
        matches = [s for s in self._sessions.values()
                   if product_id is not None and s["product_id"] == product_id and s["subtask_id"] == subtask_id]
        if active and active in matches:
            return "pause", active
        paused = max((s for s in matches if s["status"] == "paused"), key=lambda s: s["id"], default=None)
        if paused:  # db.start resumes the newest paused one
            return "resume", paused
        finished = next((s for s in matches if s["status"] == "stopped"), None)
        return ("restart", finished) if finished else ("start", None)

    def _stop_target(self):
        """Session «Завершить» closes: the running one, else the paused one in the fields, else the selected."""
        mode, target = self._intent()
        selected = self._sessions.get(self._selected_id())
        if selected and selected["status"] == "stopped":
            selected = None
        return self._active() or (target if mode == "resume" else None) or selected

    def _archive_target(self):
        """Product «Сдать» hands over: the finished pair in the fields, when nothing is running."""
        mode, target = self._intent()
        return target if mode == "restart" and self._active() is None else None

    def _on_second(self):
        target = self._archive_target()
        if target:
            self.archive_product(target["product_id"], target["product"])
        else:
            self.stop()

    def _on_main(self):
        if self._intent()[0] == "pause":
            self.pause()
        else:
            self.play()

    def _update_controls(self, active):
        mode, target = self._intent()
        switching = active is not None and mode in ("start", "resume", "restart")
        if mode == "pause":
            text, glyph, style = "Пауза", theme.G_PAUSE, "pause"
            hint = "Пауза — перерыв  ·  Завершить — закрыть сессию насовсем"
        else:
            text = ("Переключиться" if switching else "Продолжить" if mode == "resume"
                    else "Возобновить" if mode == "restart" else "Начать")
            glyph, style = theme.G_PLAY, "play"
            if mode == "empty":
                hint = "Введите продукт, чтобы начать."
            elif mode == "resume":
                hint = f"Продолжит сессию на паузе (уже {theme.fmt_human(target['total'])})."
            elif mode == "restart":
                hint = "Задача завершена — начнётся новая сессия. Готово? «Сдать» уберёт продукт из списка."
            elif self.db.find_product(self.product.currentText()) is None:
                hint = "Новый продукт — начнётся новая сессия."
            else:
                hint = "Начнётся новая сессия."
            if switching:
                hint = f"«{active['product']} · {active['subtask']}» встанет на паузу. " + hint
        if self._mode != (text, style):
            self._mode = (text, style)
            self.main_btn.setText(" " + text)
            self.main_btn.setIcon(theme.glyph_icon(glyph, "#000000"))
            self.main_btn.setProperty("mode", style)
            self.main_btn.style().unpolish(self.main_btn)
            self.main_btn.style().polish(self.main_btn)
        self.hint.setText(hint)
        self.hint.setToolTip(hint)
        archive = self._archive_target()
        second = "archive" if archive else "stop"
        if second != self._second:
            self._second = second
            self.stop_btn.setText(" Сдать" if archive else " Завершить")
            self.stop_btn.setIcon(theme.glyph_icon(theme.G_CHECK if archive else theme.G_STOP))
        if archive:
            self.stop_btn.setEnabled(True)
            self.stop_btn.setToolTip(f"Сдать «{archive['product']}»: уйдёт из списка, останется в Сводке и Журнале")
        else:
            stop = self._stop_target()
            self.stop_btn.setEnabled(stop is not None)
            self.stop_btn.setToolTip(f"Завершить «{stop['product']} · {stop['subtask']}» — сессия закроется насовсем"
                                     if stop else "Нечего завершать")

    def _update_timer(self):
        active = self._active()
        self._update_controls(active)
        mode, target = self._intent()
        shown = active or (target if mode == "resume" else None)
        self.timer_label.setText(dbm.fmt_duration(shown["total"]) if shown else "00:00:00")
        if self.mini:
            self.mini.sync()
        running = "true" if active else "false"
        if self.timer_label.property("running") != running:
            self.timer_label.setProperty("running", running)
            self.timer_label.style().unpolish(self.timer_label)
            self.timer_label.style().polish(self.timer_label)
        if active:
            self.current.setText(f"{active['product']}  •  {active['subtask']}")
            self.setWindowTitle(f"{dbm.fmt_duration(active['total'])} · {active['product']}")
        else:
            self.current.setText(f"На паузе: {shown['product']}  •  {shown['subtask']}" if shown else "Таймер не запущен")
            self.setWindowTitle(APP_TITLE)

    def _tick(self):
        at = dbm.now()
        gap = (at - self._last_tick).total_seconds()
        active = self.db.active_session()
        if active:
            pause_at, reason = None, None
            if gap > SLEEP_GAP:
                pause_at = self._last_tick
                reason = (f"Компьютер не отвечал {int(gap // 60)} мин (сон или блокировка). "
                          f"Таймер поставлен на паузу в {pause_at:%H:%M}.")
            deadline = active["deadline"]
            if deadline and at >= deadline and (pause_at is None or deadline < pause_at):
                pause_at = deadline
                reason = f"Рабочий день окончен ({deadline:%H:%M}). Таймер автоматически поставлен на паузу."
            if pause_at:
                self.db.pause_active(pause_at)
                self._notify(f"{reason}\n\n{active['product']} · {active['subtask']}")
                self.hub.changed.emit()
            elif (at - self._last_heartbeat).total_seconds() >= HEARTBEAT_EVERY:
                self.db.heartbeat(at)
                self._last_heartbeat = at
        if at.date() != self._last_tick.date():
            try:
                self.db.backup()  # the app may run for days in the tray: one copy per day
            except (OSError, sqlite3.Error):
                pass
        self._last_tick = at
        self.refresh()

    # -------------------------------------------------------------- helpers

    def _flash(self, text, warn=False):
        self.status.setText(text)
        self.status.show()
        self.status.setStyleSheet(f"color: {theme.WARN};" if warn else "")
        self._status_timer.start()

    def _notify(self, text):
        self._flash(text.replace("\n\n", " — "), warn=True)
        self.showNormal()
        self.raise_()
        QApplication.beep()
        dialogs.notify(self, APP_TITLE, text)

    def _apply_topmost(self, on, save=True):
        if self.pin_btn.isChecked() != on:
            self.pin_btn.setChecked(on)  # re-enters via toggled
            return
        self.pin_btn.setIcon(theme.glyph_icon(theme.G_PINNED if on else theme.G_PIN, theme.ACCENT if on else theme.TEXT))
        visible = self.isVisible()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        if visible:
            self.show()  # changing window flags hides the window
            theme.dark_title_bar(self)
        if save:
            self.db.set_setting("topmost", "1" if on else "0")

    def _restore_fields(self):
        """Put back the product/subtask from the last run, so continuing is one click.
        Falls back to the most recently worked session (first run, crash, deleted product)."""
        product, subtask = self.db.get_setting("last_product"), self.db.get_setting("last_subtask")
        if not product or self.db.find_product(product) is None:
            last = self.db.last_session()
            if last is None:
                return
            product, subtask = last["product"], last["subtask"]
        self._set_text(self.product, product)
        self._set_text(self.subtask, subtask or dbm.DEFAULT_SUBTASK)
        mode, target = self._intent()
        if target:
            self._select(target["id"])
        self._update_timer()

    def _restore_position(self):
        try:
            x, y = (int(v) for v in self.db.get_setting("position").split(","))
        except ValueError:
            return
        if QGuiApplication.screenAt(QPoint(x + 40, y + 40)):
            self.move(x, y)

    def showEvent(self, event):
        super().showEvent(event)
        theme.dark_title_bar(self)
        if self.mini:
            self.mini.hide()  # full window is back (expand, tray, auto-pause notice)

    def changeEvent(self, event):
        super().changeEvent(event)
        # Minimize = swap to the compact always-on-top widget; the timer keeps running.
        if event.type() == QEvent.WindowStateChange and self.isMinimized() and self.mini:
            QTimer.singleShot(0, self.hide)
            self.mini.show_mini()

    def closeEvent(self, event):
        active = self.db.active_session()
        if active:
            if not dialogs.ask(self, "Выход",
                               f"Таймер «{active['product']} · {active['subtask']}» будет поставлен на паузу.\nВыйти?"):
                event.ignore()
                return
            self.db.pause_active()
        self.db.set_setting("position", f"{self.x()},{self.y()}")
        self.db.set_setting("last_product", self.product.currentText().strip())
        self.db.set_setting("last_subtask", self.subtask.currentText().strip())
        event.accept()
        if self.tray:
            self.tray.hide()
        QApplication.quit()
