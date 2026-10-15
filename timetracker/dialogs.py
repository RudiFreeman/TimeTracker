"""Message/input dialogs with Russian buttons and a dark title bar."""
import re

from PySide6.QtCore import QRegularExpression, Qt, QTimer
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QCompleter, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QMenu, QMessageBox, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from .db import from_ts
from .theme import G_DELETE, WARN, dark_title_bar, fmt_tokens, glyph_icon

BUTTON_TEXT = {QMessageBox.Yes: "Да", QMessageBox.No: "Нет", QMessageBox.Ok: "OK", QMessageBox.Cancel: "Отмена"}


def _box(parent, icon, title, text, buttons, default=None):
    box = QMessageBox(icon, title, text, buttons, parent)
    for button, label in BUTTON_TEXT.items():
        if box.button(button):
            box.button(button).setText(label)
    if default:
        box.setDefaultButton(default)
    box.winId()  # create the native window so the title bar can be themed before it shows
    dark_title_bar(box)
    return box


def ask(parent, title, text, warning=False):
    icon = QMessageBox.Warning if warning else QMessageBox.Question
    box = _box(parent, icon, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
    return box.exec() == QMessageBox.Yes


def error(parent, title, text):
    _box(parent, QMessageBox.Critical, title, text, QMessageBox.Ok).exec()


def notify(parent, title, text):
    """Non-blocking information box (timers keep running while it is open)."""
    box = _box(parent, QMessageBox.Information, title, text, QMessageBox.Ok)
    box.setModal(False)
    box.setAttribute(Qt.WA_DeleteOnClose)
    box.show()
    box.raise_()
    return box


def ask_text(parent, title, label, initial=""):
    dlg = QInputDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setLabelText(label)
    dlg.setTextValue(initial)
    dlg.setOkButtonText("OK")
    dlg.setCancelButtonText("Отмена")
    dlg.resize(360, dlg.sizeHint().height())
    dlg.winId()
    dark_title_bar(dlg)
    if dlg.exec():
        return dlg.textValue().strip()
    return None


def confirm_archive(parent, name, open_count):
    """Ask before marking a product finished («сдан»)."""
    text = f"Сдать «{name}»?\nОн уйдёт из списка и подсказок, но останется в Сводке и Журнале."
    if open_count:
        text += f"\n\nНезавершённые сессии ({open_count}) будут завершены."
    return ask(parent, "Продукт сдан", text)


def suggest_combo(names, text, placeholder):
    """Editable combo with 'contains' suggestions, like the timer's product field."""
    combo = QComboBox(editable=True, insertPolicy=QComboBox.NoInsert, maxVisibleItems=12)
    combo.addItems(names)
    combo.setEditText(text)
    combo.lineEdit().setPlaceholderText(placeholder)
    completer = QCompleter(combo.model(), combo)
    completer.setFilterMode(Qt.MatchContains)
    completer.setCaseSensitivity(Qt.CaseInsensitive)
    completer.setCompletionMode(QCompleter.PopupCompletion)
    completer.popup().setObjectName("completer")
    combo.setCompleter(completer)
    return combo


class NewProductDialog(QDialog):
    """Name + subtask for a new product. Enter = «Создать и начать»."""

    def __init__(self, parent, products, subtasks, subtask):
        super().__init__(parent)
        self._existing = {name.casefold(): name for name in products}
        self._just_completed = False
        self.start = False
        self.setWindowTitle("Новый продукт")
        self.setMinimumWidth(380)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.setColumnStretch(1, 1)
        self.name = QLineEdit(placeholderText="Название нового продукта")
        self.name.textChanged.connect(self._check)
        self.subtask = suggest_combo(subtasks, subtask, "Тип работы")
        self.subtask.completer().activated.connect(self._mark_completed)
        for row, (text, widget) in enumerate((("Название", self.name), ("Подзадача", self.subtask))):
            form.addWidget(QLabel(text, objectName="secondary"), row, 0)
            form.addWidget(widget, row, 1)
        root.addLayout(form)

        self.note = QLabel(objectName="hint", wordWrap=True)
        self.note.hide()
        root.addWidget(self.note)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.start_btn = QPushButton("Создать и начать", objectName="accent", autoDefault=False)
        self.create_btn = QPushButton("Создать", autoDefault=False)
        cancel = QPushButton("Отмена", autoDefault=False)
        self.start_btn.clicked.connect(lambda: self._done(True))
        self.create_btn.clicked.connect(lambda: self._done(False))
        cancel.clicked.connect(self.reject)
        for button in (self.start_btn, self.create_btn, cancel):
            buttons.addWidget(button)
        root.addLayout(buttons)

        self.name.setFocus()
        self.winId()
        dark_title_bar(self)

    def _mark_completed(self, *_):
        # Enter that picks a subtask suggestion must not also submit the dialog.
        self._just_completed = True
        QTimer.singleShot(0, lambda: setattr(self, "_just_completed", False))

    def _existing_name(self):
        return self._existing.get(self.name.text().strip().casefold())

    def _check(self):
        existing = self._existing_name()
        self.note.setVisible(bool(existing))
        self.note.setText(f"Продукт «{existing}» уже есть — он будет выбран, новый не создаётся." if existing else "")
        self.start_btn.setText("Выбрать и начать" if existing else "Создать и начать")
        self.create_btn.setText("Выбрать" if existing else "Создать")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if not self._just_completed:
                self._done(True)
            return
        super().keyPressEvent(event)

    def values(self):
        """(name, subtask) — name in the existing spelling if the product already exists."""
        return self._existing_name() or self.name.text().strip(), self.subtask.currentText().strip()

    def _done(self, start):
        if not self.name.text().strip():
            self.note.setText("Введите название продукта.")
            self.note.show()
            self.name.setFocus()
            return
        self.start = start
        self.accept()


class TokenDialog(QDialog):
    """Product + model + token count, with the product's earlier records below.
    Enter moves to the next field; Enter in the count saves.

    history(product_name) -> token records ({id, model, tokens, created_at}), newest first;
    delete(record_id) removes one.
    """

    def __init__(self, parent, products, product, models, model, history, delete):
        super().__init__(parent)
        self._history = history
        self._delete = delete
        self.setWindowTitle("Токены")
        self.setMinimumWidth(420)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        form = QGridLayout()
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        form.setColumnStretch(1, 1)
        self.product = suggest_combo(products, product, "Название продукта")
        self.model = suggest_combo(models, model, "Например, ElevenLabs Multilingual v2")
        self.tokens = QLineEdit(placeholderText="Сколько токенов израсходовано")
        self.tokens.setValidator(QRegularExpressionValidator(QRegularExpression(r"[\d\s]{0,15}"), self.tokens))
        for row, (text, widget) in enumerate((("Продукт", self.product), ("Модель", self.model), ("Токены", self.tokens))):
            form.addWidget(QLabel(text, objectName="secondary"), row, 0)
            form.addWidget(widget, row, 1)
        root.addLayout(form)

        self.history_title = QLabel(objectName="secondary", wordWrap=True)
        root.addWidget(self.history_title)
        self.records = QTreeWidget(objectName="summary")
        self.records.setColumnCount(3)
        self.records.setHeaderLabels(["Дата", "Модель", "Токены"])
        self.records.setRootIsDecorated(False)
        self.records.setIndentation(0)
        self.records.setUniformRowHeights(True)
        self.records.setSelectionMode(QAbstractItemView.SingleSelection)
        self.records.setFixedHeight(180)
        self.records.setToolTip("Двойной клик — взять эту модель  ·  правый клик — удалить запись")
        header = self.records.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.Fixed)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Fixed)
        self.records.setColumnWidth(0, 120)
        self.records.setColumnWidth(2, 90)
        self.records.headerItem().setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
        self.records.setContextMenuPolicy(Qt.CustomContextMenu)
        self.records.customContextMenuRequested.connect(self._records_menu)
        self.records.itemDoubleClicked.connect(self._use_model)
        root.addWidget(self.records)
        self.product.editTextChanged.connect(lambda _: self._load_history())
        self._load_history()

        self.error = QLabel(objectName="hint", wordWrap=True)
        self.error.setStyleSheet(f"color: {WARN};")
        self.error.hide()
        root.addWidget(self.error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        save = QPushButton("Добавить", objectName="accent", autoDefault=False)
        cancel = QPushButton("Отмена", autoDefault=False)
        save.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(save)
        buttons.addWidget(cancel)
        root.addLayout(buttons)

        # Start where typing is needed: usually only the count is missing.
        first_empty = next((w for w in (self.product, self.model) if not w.currentText().strip()), self.tokens)
        first_empty.setFocus()
        self.winId()
        dark_title_bar(self)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if self.tokens.hasFocus():
                self._save()
            else:
                self.focusNextChild()  # also after picking a suggestion with Enter
            return
        super().keyPressEvent(event)

    def _load_history(self):
        product = self.product.currentText().strip()
        rows = self._history(product)
        self.records.clear()
        for row in rows:
            item = QTreeWidgetItem([f"{from_ts(row['created_at']):%d.%m.%Y %H:%M}", row["model"], fmt_tokens(row["tokens"])])
            item.setData(0, Qt.UserRole, row["id"])
            item.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
            self.records.addTopLevelItem(item)
        self.records.setVisible(bool(rows))
        if not product:
            self.history_title.setText("Укажите продукт, чтобы увидеть уже добавленные токены.")
        elif not rows:
            self.history_title.setText(f"К «{product}» токены ещё не добавлялись.")
        else:
            by_model = {}
            for row in rows:
                by_model[row["model"]] = by_model.get(row["model"], 0) + row["tokens"]
            parts = ",  ".join(f"{m} — {fmt_tokens(n)}" for m, n in sorted(by_model.items(), key=lambda kv: -kv[1]))
            total = fmt_tokens(sum(by_model.values()))
            self.history_title.setText(f"Уже добавлено: {total}" + (f"  ({parts})" if len(by_model) > 1 else ""))
        self.adjustSize()

    def _use_model(self, item):
        self.model.setEditText(item.text(1))
        self.tokens.setFocus()

    def _records_menu(self, pos):
        item = self.records.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        menu.addAction(glyph_icon(G_DELETE), "Удалить запись…", lambda: self._delete_record(item))
        menu.exec(self.records.viewport().mapToGlobal(pos))

    def _delete_record(self, item):
        if ask(self, "Удалить запись", f"Удалить запись «{item.text(1)}: {item.text(2)} токенов» от {item.text(0)}?",
               warning=True):
            self._delete(item.data(0, Qt.UserRole))
            self._load_history()

    def values(self):
        """(product, model, tokens); tokens is 0 if not entered."""
        digits = re.sub(r"\D", "", self.tokens.text())
        return self.product.currentText().strip(), self.model.currentText().strip(), int(digits) if digits else 0

    def _save(self):
        product, model, tokens = self.values()
        for ok, text, widget in ((product, "Укажите продукт.", self.product),
                                 (model, "Укажите модель.", self.model),
                                 (tokens > 0, "Введите количество токенов.", self.tokens)):
            if not ok:
                self.error.setText(text)
                self.error.show()
                widget.setFocus()
                return
        self.accept()
