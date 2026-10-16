"""Manual time editing: fix/move a journal entry, add forgotten time."""
from datetime import datetime, time as dtime, timedelta

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (
    QDateEdit, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton, QTimeEdit, QVBoxLayout, QWidget,
)

from . import db as dbm
from . import theme
from .dialogs import ask, dark_title_bar, suggest_combo


def time_edit(value):
    edit = QTimeEdit(QTime(value.hour, value.minute), displayFormat="HH:mm")
    edit.setFixedWidth(70)
    return edit


def resolve_names(parent, database, product, subtask):
    """Product/subtask ids for the typed names, offering to create missing ones; None if cancelled."""
    product_id = database.find_product(product)
    if product_id is None:
        if not ask(parent, "Новая задача", f"Задачи «{product}» ещё нет.\nСоздать её?"):
            return None
        product_id = database.get_or_create_product(product)
    subtask_id = database.find_subtask(subtask)
    if subtask_id is None:
        if not ask(parent, "Новая подзадача", f"Подзадачи «{subtask}» нет в списке.\nСоздать её?"):
            return None
        subtask_id = database.create_subtask(subtask)
    return product_id, subtask_id


def overlap_text(hit):
    return (f"Пересекается с «{hit['product']} · {hit['subtask']}» "
            f"({hit['start']:%d.%m %H:%M} – {hit['end']:%H:%M}).")


class _Form(QDialog):
    """Shared frame: grid of fields, red error line, buttons."""

    def __init__(self, parent, title, width):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(width)
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(16, 14, 16, 12)
        self.root.setSpacing(10)
        self.form = QGridLayout()
        self.form.setHorizontalSpacing(8)
        self.form.setVerticalSpacing(6)
        self.form.setColumnStretch(1, 1)
        self.root.addLayout(self.form)

    def add_field(self, row, text, widget):
        self.form.addWidget(QLabel(text, objectName="secondary"), row, 0)
        self.form.addWidget(widget, row, 1)

    def finish(self, ok_text):
        self.error = QLabel(objectName="hint", wordWrap=True)
        self.error.setStyleSheet(f"color: {theme.WARN};")
        self.error.hide()
        self.root.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        ok = QPushButton(ok_text, objectName="accent", autoDefault=False)
        cancel = QPushButton("Отмена", autoDefault=False)
        ok.clicked.connect(self._save)
        cancel.clicked.connect(self.reject)
        buttons.addWidget(ok)
        buttons.addWidget(cancel)
        self.root.addLayout(buttons)
        self.winId()
        dark_title_bar(self)

    def fail(self, text):
        self.error.setText(text)
        self.error.show()
        return False

    def _save(self):
        raise NotImplementedError


class _IntervalRow(QWidget):
    """start – end · duration · delete. Intervals crossing midnight are shown read-only."""

    def __init__(self, dialog, interval_id, start, end):
        super().__init__()
        self.dialog = dialog
        self.interval_id = interval_id
        self.orig = (start, end)
        self.day = dialog.day
        self.fixed = start.date() != end.date()
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        if self.fixed:
            label = QLabel(f"{start:%d.%m %H:%M} – {end:%d.%m %H:%M}  (через полночь — не редактируется)",
                           objectName="secondary")
            layout.addWidget(label, 1)
            self.duration = None
        else:
            self.start_edit, self.end_edit = time_edit(start), time_edit(end)
            for edit in (self.start_edit, self.end_edit):
                edit.timeChanged.connect(dialog.update_total)
            layout.addWidget(self.start_edit)
            layout.addWidget(QLabel("–", objectName="secondary"))
            layout.addWidget(self.end_edit)
            self.duration = QLabel(objectName="secondary")
            layout.addWidget(self.duration, 1)
        delete = QPushButton(objectName="flat", icon=theme.glyph_icon(theme.G_DELETE), toolTip="Удалить интервал")
        delete.clicked.connect(lambda: dialog.remove_row(self))
        layout.addWidget(delete)

    def values(self):
        """(start, end) datetimes; untouched times keep their original seconds."""
        if self.fixed:
            return self.orig
        result = []
        for edit, orig in ((self.start_edit, self.orig[0]), (self.end_edit, self.orig[1])):
            t = edit.time()
            if orig and (orig.hour, orig.minute) == (t.hour(), t.minute()):
                result.append(orig)
            else:
                result.append(datetime.combine(self.day, dtime(t.hour(), t.minute())))
        start, end = result
        if end.time() == dtime(0, 0) and end <= start:
            end += timedelta(days=1)  # "до 00:00" = до полуночи
        return start, end


class EditEntryDialog(_Form):
    """One journal entry = one session on one day: product/subtask (moving it) and that day's intervals."""

    def __init__(self, parent, database, session_id, day):
        super().__init__(parent, "Изменить запись", 440)
        self.db = database
        self.session_id = session_id
        self.day = day
        self.rows = []
        self.deleted = []
        info = database.session_info(session_id)
        self.days = database.session_days(session_id)

        self.product = suggest_combo(database.product_names(), info["product"], "Название задачи")
        self.subtask = suggest_combo(database.subtask_names(), info["subtask"], "Тип работы")
        self.add_field(0, "Задача", self.product)
        self.add_field(1, "Подзадача", self.subtask)
        self.move_note = QLabel(objectName="hint", wordWrap=True)
        self.move_note.hide()
        self.root.addWidget(self.move_note)
        for combo in (self.product, self.subtask):
            combo.editTextChanged.connect(self._update_move_note)
        self._orig_names = (info["product"].casefold(), info["subtask"].casefold())

        self.root.addWidget(QLabel(f"Интервалы за {theme.fmt_day(day)}", objectName="section"))
        self.rows_box = QVBoxLayout()
        self.rows_box.setSpacing(4)
        self.root.addLayout(self.rows_box)
        start = datetime.combine(day, dtime())
        for interval in database.day_intervals(session_id, start, start + timedelta(days=1)):
            self._add_row(interval["id"], interval["start"], interval["end"])
        bottom = QHBoxLayout()
        add = QPushButton(" Добавить интервал", objectName="flat", icon=theme.glyph_icon(theme.G_ADD))
        add.clicked.connect(self._new_row)
        bottom.addWidget(add)
        bottom.addStretch(1)
        self.total = QLabel(objectName="secondary")
        bottom.addWidget(self.total)
        self.root.addLayout(bottom)
        self.finish("Сохранить")
        self.update_total()

    def _add_row(self, interval_id, start, end):
        row = _IntervalRow(self, interval_id, start, end)
        self.rows.append(row)
        self.rows_box.addWidget(row)

    def _new_row(self):
        ends = [row.values()[1] for row in self.rows]
        start = max(ends) if ends else datetime.combine(self.day, dtime(10, 0))
        if start.date() != self.day:
            start = datetime.combine(self.day, dtime(10, 0))
        end = min(start + timedelta(hours=1), datetime.combine(self.day, dtime(23, 59)))
        self._add_row(None, start, end)
        self.update_total()

    def remove_row(self, row):
        if row.interval_id is not None:
            self.deleted.append(row.interval_id)
        self.rows.remove(row)
        row.deleteLater()
        self.update_total()
        self.adjustSize()

    def update_total(self):
        total = 0
        for row in self.rows:
            start, end = row.values()
            seconds = (end - start).total_seconds()
            total += max(0, seconds)
            if row.duration is not None:
                row.duration.setText(theme.fmt_human(seconds) if seconds > 0 else "—")
        self.total.setText(f"Итого за день: {theme.fmt_human(total)}")
        if hasattr(self, "error"):
            self.error.hide()

    def _update_move_note(self):
        names = (self.product.currentText().strip().casefold(), self.subtask.currentText().strip().casefold())
        moving = names != self._orig_names and self.days > 1
        self.move_note.setVisible(moving)
        self.move_note.setText(f"Сессия идёт {self.days} дн. — при переносе она перенесётся целиком, "
                               f"со всеми днями." if moving else "")

    def _save(self):
        product, subtask = self.product.currentText().strip(), self.subtask.currentText().strip()
        if not product or not subtask:
            return self.fail("Укажите задачу и подзадачу.")
        spans = []
        for row in self.rows:
            start, end = row.values()
            if end <= start:
                return self.fail(f"Интервал {start:%H:%M} – {end:%H:%M}: конец должен быть позже начала.")
            if end > dbm.now():
                return self.fail(f"Интервал {start:%H:%M} – {end:%H:%M} заканчивается в будущем.")
            spans.append((row, start, end))
        spans.sort(key=lambda s: s[1])
        for (_, s1, e1), (_, s2, e2) in zip(spans, spans[1:]):
            if s2 < e1:
                return self.fail(f"Интервалы {s1:%H:%M} – {e1:%H:%M} и {s2:%H:%M} – {e2:%H:%M} пересекаются.")
        mine = [row.interval_id for row in self.rows if row.interval_id] + self.deleted
        for _, start, end in spans:
            hit = self.db.find_overlap(start, end, mine)
            if hit:
                return self.fail(overlap_text(hit))
        if not spans and not ask(self, "Удалить запись", "Все интервалы удалены — удалить запись за этот день?",
                                 warning=True):
            return False
        ids = resolve_names(self, self.db, product, subtask)
        if ids is None:
            return False
        self.db.save_session_edit(self.session_id, *ids, [(row.interval_id, start, end) for row, start, end in spans],
                                  self.deleted)
        self.accept()
        return True


class ManualTimeDialog(_Form):
    """Forgotten time: date, from–to, product, subtask."""

    def __init__(self, parent, database, product, subtask):
        super().__init__(parent, "Добавить время вручную", 380)
        self.db = database
        today = dbm.now()
        self.date = QDateEdit(QDate(today.year, today.month, today.day), calendarPopup=True, displayFormat="dd.MM.yyyy")
        self.date.setMaximumDate(QDate(today.year, today.month, today.day))
        self.date.setFixedWidth(130)
        start = max(today - timedelta(hours=1), datetime.combine(today.date(), dtime()))
        self.start, self.end = time_edit(start), time_edit(today)
        span = QHBoxLayout()
        span.setSpacing(6)
        span.addWidget(self.start)
        span.addWidget(QLabel("–", objectName="secondary"))
        span.addWidget(self.end)
        self.duration = QLabel(objectName="secondary")
        span.addWidget(self.duration, 1)
        self.product = suggest_combo(database.product_names(), product, "Название задачи")
        self.subtask = suggest_combo(database.subtask_names(), subtask or dbm.DEFAULT_SUBTASK, "Тип работы")
        self.add_field(0, "Дата", self.date)
        self.form.addWidget(QLabel("Время", objectName="secondary"), 1, 0)
        self.form.addLayout(span, 1, 1)
        self.add_field(2, "Задача", self.product)
        self.add_field(3, "Подзадача", self.subtask)
        for edit in (self.start, self.end):
            edit.timeChanged.connect(self._update_duration)
        self.date.dateChanged.connect(self._update_duration)
        self.finish("Добавить")
        self._update_duration()

    def span(self):
        d = self.date.date().toPython()
        start = datetime.combine(d, self.start.time().toPython().replace(second=0))
        end = datetime.combine(d, self.end.time().toPython().replace(second=0))
        if end.time() == dtime(0, 0) and end <= start:
            end += timedelta(days=1)
        return start, end

    def _update_duration(self):
        start, end = self.span()
        seconds = (end - start).total_seconds()
        self.duration.setText(theme.fmt_human(seconds) if seconds > 0 else "—")
        if hasattr(self, "error"):
            self.error.hide()

    def _save(self):
        start, end = self.span()
        product, subtask = self.product.currentText().strip(), self.subtask.currentText().strip()
        if not product or not subtask:
            return self.fail("Укажите задачу и подзадачу.")
        if end <= start:
            return self.fail("Конец должен быть позже начала.")
        if end > dbm.now():
            return self.fail("Это время ещё не наступило.")
        hit = self.db.find_overlap(start, end)
        if hit:
            return self.fail(overlap_text(hit))
        ids = resolve_names(self, self.db, product, subtask)
        if ids is None:
            return False
        self.db.add_manual(*ids, start, end)
        self.accept()
        return True
