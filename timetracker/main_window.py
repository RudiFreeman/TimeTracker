"""Main window: sidebar + pages (day journal, product summary, settings)."""
import os
import sqlite3
from datetime import datetime

from PySide6.QtCore import QRect, QSize, Qt, QTime, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMenu, QPushButton, QScrollArea, QStackedWidget, QStyledItemDelegate,
    QTimeEdit,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from . import db as dbm
from . import dialogs, edit_dialogs, reporting, system, theme
from .about_page import AboutPage
from .delegates import DATA, Box, JournalDelegate, payload

KEY = Qt.UserRole + 1
AUTO_REFRESH_MS = 5000


def _report_dir():
    """Where «Экспорт CSV» suggests saving: next to the program; on macOS the data folder is hidden
    in ~/Library, so Documents."""
    if theme.MAC:
        return os.path.join(os.path.expanduser("~"), "Documents")
    return dbm.app_dir()


def theme_color(hex_color):
    return QBrush(QColor(hex_color))


def page_layout(widget, title):
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(28, 18, 28, 14)
    layout.setSpacing(10)
    layout.addWidget(QLabel(title, objectName="title"))
    return layout


def period_combo(default):
    combo = QComboBox()
    combo.addItems(reporting.PERIODS)
    combo.setCurrentText(default)
    combo.setMinimumWidth(170)
    return combo


def search_field():
    field = QLineEdit(placeholderText="Поиск по задаче или подзадаче", clearButtonEnabled=True)
    field.addAction(theme.glyph_icon(theme.G_SEARCH, theme.TEXT_3), QLineEdit.LeadingPosition)
    field.setMinimumWidth(180)
    field.setMaximumWidth(320)
    return field


class MainWindow(QWidget):
    def __init__(self, database, hub, timer):
        super().__init__()
        self.db = database
        self.hub = hub
        self.setObjectName("window")
        self.setWindowTitle("Time Tracker — журнал")
        self.resize(1000, 680)
        self.setMinimumSize(720, 420)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget(objectName="sidebar")
        sidebar.setFixedWidth(220)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(0, 14, 0, 14)
        side.addWidget(QLabel("  Time Tracker", objectName="section"))
        side.addSpacing(8)
        self.nav = QListWidget(objectName="nav")
        self.nav.setIconSize(QSize(16, 16))
        for glyph, text in ((theme.G_CLOCK, "Журнал"), (theme.G_CHART, "Сводка по задачам"), (theme.G_SETTINGS, "Настройки"),
                            (theme.G_INFO, "О программе")):
            self.nav.addItem(QListWidgetItem(theme.glyph_icon(glyph), "  " + text))
        side.addWidget(self.nav, 1)
        timer_btn = QPushButton(" Окно таймера", objectName="flat", icon=theme.glyph_icon(theme.G_PLAY))
        timer_btn.clicked.connect(lambda: (timer.showNormal(), timer.raise_(), timer.activateWindow()))
        side.addWidget(timer_btn, 0, Qt.AlignLeft)
        layout.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.pages = [JournalPage(database, hub, timer), SummaryPage(database, hub), SettingsPage(database, hub), AboutPage(timer)]
        for page in self.pages:
            if isinstance(page, SettingsPage):
                # Settings is taller than the default window: scroll instead of squeezing the cards.
                scroll = QScrollArea(widgetResizable=True, frameShape=QFrame.NoFrame)
                scroll.setWidget(page)
                self.stack.addWidget(scroll)
            else:
                self.stack.addWidget(page)
        layout.addWidget(self.stack, 1)

        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)
        hub.changed.connect(self.refresh_current)
        self._auto = QTimer(self, interval=AUTO_REFRESH_MS, timeout=self._auto_refresh)
        self._auto.start()

    def _on_nav(self, row):
        self.stack.setCurrentIndex(row)
        self.refresh_current()

    def refresh_current(self):
        if self.isVisible():
            self.pages[self.stack.currentIndex()].refresh()

    def _auto_refresh(self):
        # Only the journal/summary show running time; skip when nothing is running.
        if self.isVisible() and not self.isMinimized() and self.db.active_session():
            page = self.pages[self.stack.currentIndex()]
            if not isinstance(page, SettingsPage):
                page.refresh()

    def show_product(self, index, product):
        """Journal (0) or Summary (1) for all time, filtered to one product and expanded."""
        page = self.pages[index]
        page.period.setCurrentText(reporting.ALL_TIME)
        page.search.setText(product)
        self.show_page(index)
        page.expand_all()

    def show_page(self, index):
        self.nav.setCurrentRow(index)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.refresh_current()

    def showEvent(self, event):
        super().showEvent(event)
        theme.dark_title_bar(self)
        self.refresh_current()


# ======================================================================= journal

class JournalPage(QWidget):
    def __init__(self, database, hub, timer):
        super().__init__()
        self.db = database
        self.hub = hub
        self.timer = timer
        self._initialized = False
        layout = page_layout(self, "Журнал")

        bar = QHBoxLayout()
        self.period = period_combo(reporting.LAST_30)
        self.period.currentTextChanged.connect(self.refresh)
        self.search = search_field()
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.period)
        bar.addWidget(self.search, 1)
        bar.addStretch(0)
        for text, expand in (("Развернуть", True), ("Свернуть", False)):
            button = QPushButton(text, objectName="flat")
            button.clicked.connect(lambda _=False, e=expand: self._set_all(e))
            bar.addWidget(button)
        manual = QPushButton(" Время вручную", icon=theme.glyph_icon(theme.G_ADD),
                             toolTip="Добавить забытое время (таймер не был включён)")
        manual.clicked.connect(self._add_manual)
        bar.addWidget(manual)
        layout.addLayout(bar)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(0)
        self.tree.setRootIsDecorated(False)
        self.delegate = JournalDelegate(self.tree)
        self.tree.setItemDelegate(self.delegate)
        self.tree.setSelectionMode(QAbstractItemView.NoSelection)
        self.tree.setFocusPolicy(Qt.NoFocus)
        self.tree.setMouseTracking(True)
        self.tree.setExpandsOnDoubleClick(False)
        self.tree.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.itemClicked.connect(self._on_click)
        self.tree.itemDoubleClicked.connect(self._on_double_click)
        self.tree.customContextMenuRequested.connect(self._menu)
        layout.addWidget(self.tree, 1)

        self.empty = QLabel("За этот период записей нет", objectName="hint", alignment=Qt.AlignCenter)
        layout.addWidget(self.empty)
        self.total = QLabel(objectName="secondary")
        layout.addWidget(self.total)

    def refresh(self):
        at = dbm.now()
        start, end = reporting.period_bounds(self.period.currentText(), at.date())
        days = reporting.build_days(reporting.filter_rows(self.db.report_rows(start, end, at), self.search.text()))
        self.delegate.workday = self.db.workday()
        day_tip = "Полоса — работа за сутки; светлая часть и засечки — рабочий день {:%H:%M}–{:%H:%M}".format(
            *self.delegate.workday)

        expanded = set()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.isExpanded():
                expanded.add(item.data(0, KEY))
        scroll = self.tree.verticalScrollBar().value()

        self.tree.setUpdatesEnabled(False)
        self.tree.clear()
        for index, day in enumerate(days):
            key = day["date"].isoformat()
            item = QTreeWidgetItem()
            item.setData(0, DATA, Box({"kind": "day", "day": day}))
            item.setData(0, KEY, key)
            item.setToolTip(0, day_tip)
            for entry in day["entries"]:
                child = QTreeWidgetItem()
                child.setData(0, DATA, Box({"kind": "entry", "entry": entry, "day": day["date"]}))
                spans = "\n".join(f"{s:%H:%M} – {e:%H:%M}" for s, e in entry["intervals"])
                child.setToolTip(0, f"{entry['product']} · {entry['subtask']}\n{spans}\n\nДвойной клик — продолжить  ·  правый клик — изменить")
                item.addChild(child)
            self.tree.addTopLevelItem(item)
            if key in expanded or (not self._initialized and index == 0):
                item.setExpanded(True)
        self.tree.setUpdatesEnabled(True)
        self.tree.verticalScrollBar().setValue(scroll)
        self._initialized = True

        total = sum(d["total"] for d in days)
        self.empty.setVisible(not days)
        self.total.setText(f"Итого: {theme.fmt_human(total)}  ·  {reporting.hours(total)} ч  ·  дней: {len(days)}")

    def expand_all(self):
        self._set_all(True)

    def _set_all(self, expanded):
        for i in range(self.tree.topLevelItemCount()):
            self.tree.topLevelItem(i).setExpanded(expanded)

    def _on_click(self, item):
        if payload(self.tree.indexFromItem(item))["kind"] == "day":
            item.setExpanded(not item.isExpanded())

    def _on_double_click(self, item):
        data = payload(self.tree.indexFromItem(item))
        if data["kind"] == "entry":
            self._continue(data["entry"])

    def _continue(self, entry):
        self.timer.continue_task(entry["session_id"], entry["product_id"], entry["subtask_id"], entry["status"])

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        data = payload(self.tree.indexFromItem(item)) if item else None
        if not data or data["kind"] != "entry":
            return
        entry = data["entry"]
        menu = QMenu(self)
        menu.addAction(theme.glyph_icon(theme.G_EDIT), "Изменить…", lambda: self._edit(entry, data["day"]))
        menu.addSeparator()
        if entry["status"] != "active":
            menu.addAction(theme.glyph_icon(theme.G_PLAY), "Продолжить", lambda: self._continue(entry))
        else:
            menu.addAction(theme.glyph_icon(theme.G_PAUSE), "Пауза", self.timer.pause)
        if entry["status"] != "stopped":
            menu.addAction(theme.glyph_icon(theme.G_STOP), "Завершить сессию", lambda: self.timer.stop(entry["session_id"]))
        menu.addSeparator()
        menu.addAction(theme.glyph_icon(theme.G_DELETE), "Удалить сессию…", lambda: self._delete(entry))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _edit(self, entry, day):
        if entry["status"] == "active":
            dialogs.error(self, "Изменить запись", "Эта запись сейчас идёт.\nПоставьте её на паузу, затем измените.")
            return
        if edit_dialogs.EditEntryDialog(self, self.db, entry["session_id"], day).exec():
            self.hub.changed.emit()

    def _add_manual(self):
        product = self.timer.product.currentText().strip()
        subtask = self.timer.subtask.currentText().strip()
        if edit_dialogs.ManualTimeDialog(self, self.db, product, subtask).exec():
            self.hub.changed.emit()

    def _delete(self, entry):
        if dialogs.ask(self, "Удалить сессию",
                       f"Удалить сессию «{entry['product']} · {entry['subtask']}» целиком (все дни)?\nЭто нельзя отменить.",
                       warning=True):
            self.db.delete_session(entry["session_id"])
            self.hub.changed.emit()


# ======================================================================= summary

SEPARATOR = "sep"  # KEY of the thin line between products in work and finished ones
SUMMARY_ROW = 28
SEPARATOR_ROW = 11


class SummaryDelegate(QStyledItemDelegate):
    """Row heights for the summary (QSS item height would also inflate the separator)."""

    def sizeHint(self, option, index):
        size = super().sizeHint(option, index)
        return QSize(size.width(), SEPARATOR_ROW if index.data(KEY) == SEPARATOR else SUMMARY_ROW)


class SummaryTree(QTreeWidget):
    """Tree with hand-drawn expand arrows (QSS branch images sit off-center and jump when toggled)
    and a thin separator row."""

    def drawBranches(self, painter, rect, index):
        item = self.itemFromIndex(index)
        if item and item.isSelected():
            painter.fillRect(rect, QColor("#333333"))
        if not item or item.childCount() == 0:
            return
        # Pre-rendered glyph (grayscale antialiasing: drawText on a dark row gives colored ClearType fringes).
        pix = theme.glyph_pixmap(theme.G_DOWN if item.isExpanded() else theme.G_RIGHT, theme.TEXT_2, 12)
        x = rect.right() - self.indentation() + 1 + (self.indentation() - 12) // 2
        painter.drawPixmap(x, rect.top() + (rect.height() - 12) // 2, pix)

    def drawRow(self, painter, option, index):
        item = self.itemFromIndex(index)
        if item and item.data(0, KEY) == SEPARATOR:
            y = option.rect.center().y()
            painter.save()
            painter.setPen(QPen(QColor(theme.BORDER), 1))
            painter.drawLine(option.rect.left() + 4, y, option.rect.right() - 4, y)
            painter.restore()
            return
        super().drawRow(painter, option, index)


class SummaryPage(QWidget):
    COLUMNS = ["Задача / подзадача / сессия", "Время", "Часы", "Минуты", "Сессий", "Токены", "Последняя работа"]
    TOKENS_COL = 5

    def __init__(self, database, hub):
        super().__init__()
        self.db = database
        self.hub = hub
        self._rows = []
        self._token_rows = []
        self._archived = set()
        layout = page_layout(self, "Сводка по задачам")

        bar = QHBoxLayout()
        self.period = period_combo(reporting.ALL_TIME)
        self.period.currentTextChanged.connect(self.refresh)
        self.search = search_field()
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(self.period)
        bar.addWidget(self.search, 1)
        bar.addStretch(0)
        for text, expand in (("Развернуть", True), ("Свернуть", False)):
            button = QPushButton(text, objectName="flat")
            button.clicked.connect(lambda _=False, e=expand: self.tree.expandAll() if e else self.tree.collapseAll())
            bar.addWidget(button)
        export = QPushButton(" Экспорт CSV", icon=theme.glyph_icon(theme.G_EXPORT))
        export.clicked.connect(self.export_csv)
        bar.addWidget(export)
        layout.addLayout(bar)

        self.tree = SummaryTree(objectName="summary")
        self.tree.setColumnCount(len(self.COLUMNS))
        self.tree.setHeaderLabels(self.COLUMNS)
        self.tree.setIndentation(18)
        self.tree.setMouseTracking(True)
        self.tree.setUniformRowHeights(False)  # the separator row is thinner
        self.tree.setItemDelegate(SummaryDelegate(self.tree))
        self.tree.itemSelectionChanged.connect(self._update_archive_button)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for col, width in ((1, 90), (2, 70), (3, 70), (4, 70), (5, 100), (6, 140)):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
            self.tree.setColumnWidth(col, width)
            self.tree.headerItem().setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(self.tree, 1)
        footer = QHBoxLayout()
        self.total = QLabel(objectName="secondary")
        footer.addWidget(self.total, 1)
        self.archive_btn = QPushButton(" Сдана", icon=theme.glyph_icon(theme.G_CHECK))
        self.archive_btn.clicked.connect(self._toggle_selected_archive)
        footer.addWidget(self.archive_btn)
        footer.addSpacing(8)
        self.show_archived = QCheckBox("Показывать сданные")
        self.show_archived.toggled.connect(self.refresh)
        footer.addWidget(self.show_archived)
        layout.addLayout(footer)

    def expand_all(self):
        self.tree.expandAll()

    def _filtered(self):
        return reporting.filter_rows(self._rows, self.search.text())

    def _item(self, parent, key, texts, bold=False, meta=None, icon=None):
        item = QTreeWidgetItem(parent, texts)
        item.setData(0, KEY, key)
        if meta:
            item.setData(0, DATA, Box(meta))
        if icon:
            item.setIcon(0, icon)
        for col in range(1, len(texts)):
            item.setTextAlignment(col, Qt.AlignRight | Qt.AlignVCenter)
        if bold:
            font = QFont(item.font(0))
            font.setBold(True)
            for col in range(len(texts)):
                item.setFont(col, font)
        return item

    def _all_items(self):
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    def refresh(self):
        at = dbm.now()
        start, end = reporting.period_bounds(self.period.currentText(), at.date())
        self._rows = self.db.report_rows(start, end, at)
        products = reporting.aggregate(self._filtered())
        self._token_rows = self.db.token_rows(start, end)
        tokens = reporting.aggregate_tokens(reporting.filter_rows(self._token_rows, self.search.text(), "model"))
        for product_id, t in tokens.items():  # products with tokens but no time in this period
            products.setdefault(product_id, {"name": t["name"], "total": 0, "last": t["last"], "subtasks": {}})
        self._archived = self.db.archived_ids()
        if not self.show_archived.isChecked():
            products = {k: v for k, v in products.items() if k not in self._archived}
            tokens = {k: v for k, v in tokens.items() if k not in self._archived}

        expanded = {item.data(0, KEY) for item in self._all_items() if item.isExpanded()}
        selected = self.tree.currentItem().data(0, KEY) if self.tree.currentItem() else None
        scroll = self.tree.verticalScrollBar().value()
        self.tree.setUpdatesEnabled(False)
        self.tree.blockSignals(True)
        self.tree.clear()
        grand = 0
        grand_tokens = sum(t["total"] for t in tokens.values())
        status_text = {"active": "  ▶ идёт", "paused": "  ❚❚ пауза", "stopped": ""}
        order = sorted(products.items(), key=lambda kv: kv[1]["last"], reverse=True)
        order.sort(key=lambda kv: kv[0] in self._archived)  # stable: finished ones go last
        separator_done = False
        for product_id, product in order:
            if product_id in self._archived and not separator_done and len(order) > 1 and order[0][0] not in self._archived:
                separator_done = True
                sep = QTreeWidgetItem(self.tree)
                sep.setData(0, KEY, SEPARATOR)
                sep.setFlags(Qt.NoItemFlags)
                sep.setSizeHint(0, QSize(0, 11))
            grand += product["total"]
            sessions = sum(len(t["sessions"]) for t in product["subtasks"].values())
            p_tokens = tokens.get(product_id)
            last = max(product["last"], p_tokens["last"]) if p_tokens else product["last"]
            p_item = self._item(
                self.tree, f"p{product_id}",
                [product["name"], *([theme.fmt_human(product["total"]), reporting.hours(product["total"]),
                                     reporting.minutes(product["total"]), str(sessions)]
                                    if sessions else ["", "", "", ""]),
                 theme.fmt_tokens(p_tokens["total"]) if p_tokens else "", f"{last:%d.%m.%Y %H:%M}"],
                bold=True, meta=("product", product_id, product["name"]), icon=theme.dot_icon(theme.product_color(product_id)),
            )
            if product_id in self._archived:
                p_item.setText(0, f"{product['name']}  ·  сдана")
                for col in range(self.tree.columnCount()):
                    p_item.setForeground(col, theme_color(theme.TEXT_3))
            for subtask_id, subtask in sorted(product["subtasks"].items(), key=lambda kv: -kv[1]["total"]):
                t_item = self._item(
                    p_item, f"p{product_id}t{subtask_id}",
                    [subtask["name"], theme.fmt_human(subtask["total"]), reporting.hours(subtask["total"]),
                     reporting.minutes(subtask["total"]), str(len(subtask["sessions"])), "",
                     f"{subtask['last']:%d.%m.%Y %H:%M}"],
                )
                for session_id, s in sorted(subtask["sessions"].items(), key=lambda kv: kv[1]["first"], reverse=True):
                    label = f"Сессия от {s['first']:%d.%m.%Y %H:%M}"
                    if len(s["days"]) > 1:
                        label += f"  ({len(s['days'])} дн.)"
                    s_item = self._item(
                        t_item, f"s{session_id}",
                        [label + status_text[s["status"]], theme.fmt_human(s["total"]), reporting.hours(s["total"]),
                         reporting.minutes(s["total"]), "", "", f"{s['last']:%d.%m.%Y %H:%M}"],
                        meta=("session", session_id, None),
                    )
                    s_item.setForeground(0, theme_color(theme.TEXT_2))
                    if len(s["days"]) > 1:
                        for day, seconds in sorted(s["days"].items()):
                            d_item = self._item(s_item, f"s{session_id}d{day}",
                                                [theme.fmt_day(day), theme.fmt_human(seconds), reporting.hours(seconds),
                                                 reporting.minutes(seconds), "", "", ""])
                            d_item.setForeground(0, theme_color(theme.TEXT_3))
            if p_tokens:
                self._token_items(p_item, product_id, p_tokens)
        for item in self._all_items():
            if item.data(0, KEY) in expanded:
                item.setExpanded(True)
            if selected and item.data(0, KEY) == selected:
                self.tree.setCurrentItem(item)
        self.tree.blockSignals(False)
        self._update_archive_button()
        self.tree.setUpdatesEnabled(True)
        self.tree.verticalScrollBar().setValue(scroll)
        text = (f"Итого: {theme.fmt_human(grand)}  ·  {reporting.hours(grand)} ч  ·  {reporting.minutes(grand)} мин"
                f"  ·  задач: {len(products)}")
        if grand_tokens:
            text += f"  ·  токенов: {theme.fmt_tokens(grand_tokens)}"
        self.total.setText(text)

    def _token_items(self, p_item, product_id, p_tokens):
        """One row per model under the product, with each logged record inside."""
        icon = theme.glyph_icon(theme.G_TOKENS, theme.TEXT_2)
        for model, m in sorted(p_tokens["models"].items(), key=lambda kv: -kv[1]["total"]):
            m_item = self._item(p_item, f"p{product_id}m{model}",
                                [model, "", "", "", "", theme.fmt_tokens(m["total"]), f"{m['last']:%d.%m.%Y %H:%M}"],
                                icon=icon)
            m_item.setToolTip(0, f"Токены · {model}: записей {len(m['entries'])}")
            for entry in reversed(m["entries"]):
                e_item = self._item(m_item, f"u{entry['id']}",
                                    [f"Запись от {entry['at']:%d.%m.%Y %H:%M}", "", "", "", "",
                                     theme.fmt_tokens(entry["tokens"]), ""],
                                    meta=("tokens", entry["id"], model))
                e_item.setForeground(0, theme_color(theme.TEXT_2))

    def export_csv(self):
        rows = self._filtered()
        if not rows:
            dialogs.error(self, "Экспорт", "За выбранный период нет данных.")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт", os.path.join(_report_dir(), f"time_report_{dbm.now():%Y-%m-%d}.csv"), "CSV (*.csv)"
        )
        if not path:
            return
        reporting.write_csv(path, rows)
        if dialogs.ask(self, "Экспорт", f"Отчёт сохранён:\n{path}\n\nОткрыть файл?"):
            system.open_path(path)

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        meta = payload(self.tree.indexFromItem(item)) if item else None
        if not meta:
            return
        kind, item_id, name = meta
        menu = QMenu(self)
        if kind == "product":
            if item_id in self._archived:
                menu.addAction(theme.glyph_icon(theme.G_PLAY), "Вернуть в работу",
                               lambda: self._set_archived(item_id, name, False))
            else:
                menu.addAction(theme.glyph_icon(theme.G_CHECK), "Отметить как сданную",
                               lambda: self._set_archived(item_id, name, True))
            menu.addAction("Переименовать задачу…", lambda: self._rename(item_id, name))
            menu.addSeparator()
            menu.addAction(theme.glyph_icon(theme.G_DELETE), "Удалить задачу со всеми сессиями…",
                           lambda: self._delete_product(item_id, name))
        elif kind == "tokens":
            menu.addAction(theme.glyph_icon(theme.G_DELETE), "Удалить запись о токенах…",
                           lambda: self._delete_tokens(item_id, name, item.text(self.TOKENS_COL)))
        else:
            menu.addAction(theme.glyph_icon(theme.G_DELETE), "Удалить сессию…", lambda: self._delete_session(item_id))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    def _rename(self, product_id, name):
        new_name = dialogs.ask_text(self, "Переименовать", "Новое название задачи:", name)
        if not new_name or new_name == name:
            return
        try:
            self.db.rename_product(product_id, new_name)
        except ValueError:
            if not dialogs.ask(self, "Объединить задачи",
                               f"Задача «{new_name}» уже существует.\nПеренести в неё все сессии «{name}»?"):
                return
            self.db.merge_products(product_id, self.db.find_product(new_name))
        self.hub.changed.emit()

    def _selected_product(self):
        """(product_id, name) of the product the current row belongs to, or None."""
        item = self.tree.currentItem()
        while item and item.parent():
            item = item.parent()
        meta = payload(self.tree.indexFromItem(item)) if item else None
        return (meta[1], meta[2]) if meta and meta[0] == "product" else None

    def _update_archive_button(self):
        product = self._selected_product()
        self.archive_btn.setEnabled(product is not None)
        archived = product is not None and product[0] in self._archived
        self.archive_btn.setText(" Вернуть в работу" if archived else " Сдана")
        self.archive_btn.setIcon(theme.glyph_icon(theme.G_PLAY if archived else theme.G_CHECK))
        self.archive_btn.setToolTip(f"«{product[1]}»" if product else "Выберите задачу в списке")

    def _toggle_selected_archive(self):
        product = self._selected_product()
        if product:
            self._set_archived(product[0], product[1], product[0] not in self._archived)

    def _set_archived(self, product_id, name, archived):
        if archived and not dialogs.confirm_archive(self, name, self.db.open_session_count(product_id)):
            return
        self.db.set_archived(product_id, archived)
        self.hub.changed.emit()

    def _delete_product(self, product_id, name):
        if dialogs.ask(self, "Удалить задачу", f"Удалить «{name}», все её сессии и записи токенов?\n"
                       "Это нельзя отменить.", warning=True):
            self.db.delete_product(product_id)
            self.hub.changed.emit()

    def _delete_tokens(self, usage_id, model, amount):
        if dialogs.ask(self, "Удалить запись", f"Удалить запись «{model}: {amount} токенов»?", warning=True):
            self.db.delete_tokens(usage_id)
            self.hub.changed.emit()

    def _delete_session(self, session_id):
        if dialogs.ask(self, "Удалить сессию", "Удалить эту сессию?\nЭто нельзя отменить.", warning=True):
            self.db.delete_session(session_id)
            self.hub.changed.emit()


# ====================================================================== settings

def card(title, hint=None):
    frame = QFrame(objectName="card")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(16, 12, 16, 14)
    layout.setSpacing(8)
    layout.addWidget(QLabel(title, objectName="section"))
    if hint:
        layout.addWidget(QLabel(hint, objectName="hint", wordWrap=True))
    return frame, layout


class SettingsPage(QWidget):
    def __init__(self, database, hub):
        super().__init__()
        self.db = database
        self.hub = hub
        layout = page_layout(self, "Настройки")

        frame, box = card("Рабочий день",
                          "Начало и конец дня отмечены на полосе времени в журнале. Если таймер забыли "
                          "выключить, в конце дня он сам встанет на паузу — лишние часы не накрутятся.")
        row = QHBoxLayout()
        enabled, limit = self.db.limit_config()
        day_start, _ = self.db.workday()
        self.day_start = QTimeEdit(QTime(day_start.hour, day_start.minute), displayFormat="HH:mm")
        self.limit_time = QTimeEdit(QTime(limit.hour, limit.minute), displayFormat="HH:mm")
        for text, edit in (("Начало", self.day_start), ("Конец", self.limit_time)):
            edit.setFixedWidth(80)
            edit.timeChanged.connect(self._save_limit)
            row.addWidget(QLabel(text, objectName="secondary"))
            row.addWidget(edit)
            row.addSpacing(12)
        row.addStretch(1)
        box.addLayout(row)
        self.limit_enabled = QCheckBox("Автоматически ставить таймер на паузу в конце дня", checked=enabled)
        self.limit_enabled.toggled.connect(self._save_limit)
        box.addWidget(self.limit_enabled)
        layout.addWidget(frame)

        frame, box = card("Подзадачи", "Удалить можно только подзадачу, по которой ещё нет сессий.")
        self.subtasks = QListWidget(objectName="plain")
        self.subtasks.setFixedHeight(150)
        box.addWidget(self.subtasks)
        row = QHBoxLayout()
        self.new_subtask = QLineEdit(placeholderText="Новая подзадача")
        self.new_subtask.returnPressed.connect(self._add_subtask)
        add = QPushButton(" Добавить", icon=theme.glyph_icon(theme.G_ADD))
        add.clicked.connect(self._add_subtask)
        delete = QPushButton(" Удалить выбранную", icon=theme.glyph_icon(theme.G_DELETE))
        delete.clicked.connect(self._delete_subtask)
        row.addWidget(self.new_subtask, 1)
        row.addWidget(add)
        row.addWidget(delete)
        box.addLayout(row)
        layout.addWidget(frame)

        frame, box = card("Запуск")
        self.autostart = QCheckBox(system.AUTOSTART_TEXT)
        if system.autostart_supported():
            self.autostart.toggled.connect(self._save_autostart)
        else:
            self.autostart.setEnabled(False)
            self.autostart.setToolTip("Доступно только в собранной программе")
        box.addWidget(self.autostart)
        layout.addWidget(frame)

        frame, box = card("Данные и резервные копии",
                          f"Вся база — один файл {'в папке ниже' if theme.MAC else 'рядом с программой'}. Раз в день её копия сохраняется в папку "
                          f"«{dbm.BACKUP_DIR}», хранятся последние {dbm.BACKUP_KEEP}.")
        path = QLabel(self.db.path, objectName="secondary", wordWrap=True)
        path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        box.addWidget(path)
        self.backup_info = QLabel(objectName="secondary")
        box.addWidget(self.backup_info)
        row = QHBoxLayout()
        open_folder = QPushButton("Открыть папку")
        open_folder.clicked.connect(lambda: system.open_path(os.path.dirname(self.db.path)))
        backup_now = QPushButton("Сделать копию сейчас")
        backup_now.clicked.connect(self._backup_now)
        open_backups = QPushButton("Папка с копиями")
        open_backups.clicked.connect(self._open_backups)
        for button in (open_folder, backup_now, open_backups):
            row.addWidget(button)
        row.addStretch(1)
        box.addLayout(row)
        layout.addWidget(frame)
        layout.addStretch(1)

    def refresh(self):
        self.subtasks.clear()
        self.subtasks.addItems(self.db.subtask_names())
        self.autostart.blockSignals(True)
        self.autostart.setChecked(system.autostart_enabled())
        self.autostart.blockSignals(False)
        backups = self.db.backups()
        if backups:
            last = datetime.fromtimestamp(os.path.getmtime(backups[0]))
            self.backup_info.setText(f"Последняя копия: {last:%d.%m.%Y %H:%M}  ·  копий: {len(backups)}")
        else:
            self.backup_info.setText("Копий пока нет.")

    def _save_autostart(self, on):
        try:
            system.set_autostart(on)
        except OSError as exc:
            dialogs.error(self, "Автозапуск", f"Не удалось изменить автозапуск:\n{exc}")
        self.refresh()

    def _backup_now(self):
        try:
            path = self.db.backup(force=True)
        except (OSError, sqlite3.Error) as exc:
            dialogs.error(self, "Резервная копия", f"Не удалось сделать копию:\n{exc}")
            return
        self.refresh()
        dialogs.notify(self, "Резервная копия", f"Копия сохранена:\n{path}")

    def _open_backups(self):
        os.makedirs(self.db.backup_dir(), exist_ok=True)
        system.open_path(self.db.backup_dir())

    def _save_limit(self, *_):
        self.db.set_setting("limit_enabled", "1" if self.limit_enabled.isChecked() else "0")
        self.db.set_setting("day_start", self.day_start.time().toString("HH:mm"))
        self.db.set_setting("limit_time", self.limit_time.time().toString("HH:mm"))
        self.hub.changed.emit()  # journal timeline markers

    def _add_subtask(self):
        name = self.new_subtask.text().strip()
        if not name:
            return
        self.db.create_subtask(name)
        self.new_subtask.clear()
        self.hub.changed.emit()

    def _delete_subtask(self):
        item = self.subtasks.currentItem()
        if not item:
            return
        try:
            self.db.delete_subtask(item.text())
        except ValueError as exc:
            dialogs.error(self, "Нельзя удалить", str(exc))
            return
        self.hub.changed.emit()
