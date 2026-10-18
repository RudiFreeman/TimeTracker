"""Окно таймера (offscreen, без показа на экране): поля-выбор, группировка списка по задачам, кнопки."""
import pytest
from PySide6.QtCore import Qt

from timetracker.delegates import payload
from timetracker.timer_window import Hub, PickCombo, TimerWindow
from conftest import at


@pytest.fixture
def window(qapp, db):
    w = TimerWindow(db, Hub())
    yield w
    w._ticker.stop()
    w.deleteLater()


def list_rows(w):
    return [payload(w.list.indexFromItem(w.list.item(i))) for i in range(w.list.count())]


# --- PickCombo: поле «только выбор» ------------------------------------------------

def test_pick_combo_not_editable(qapp):
    combo = PickCombo("Выберите задачу")
    assert not combo.isEditable()
    assert combo.placeholderText() == "Выберите задачу"


def test_pick_combo_set_text(qapp):
    combo = PickCombo("")
    combo.set_names(["DAC 520SV", "TitanFlex"])
    combo.set_text("titanflex")  # регистр не важен — берётся имя из списка
    assert combo.currentText() == "TitanFlex"
    combo.set_text("Удалённая")  # имени нет в списке — поле очищается, в список НЕ добавляется
    assert combo.currentIndex() == -1 and combo.count() == 2
    combo.set_text("DAC 520SV")
    combo.set_text("")
    assert combo.currentIndex() == -1 and combo.currentText() == ""


def test_pick_combo_ignores_wheel(qapp):
    """Колесо мыши над полем не должно незаметно переключать задачу (code-review 2.3.0)."""
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QWheelEvent
    combo = PickCombo("")
    combo.set_names(["A", "B", "C"])
    combo.set_text("B")
    event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, -120), Qt.NoButton, Qt.NoModifier,
                        Qt.NoScrollPhase, False)
    qapp.sendEvent(combo, event)
    assert combo.currentText() == "B"


def test_pick_combo_set_names_keeps_choice(qapp):
    combo = PickCombo("")
    combo.set_names(["A", "B"])
    combo.set_text("B")
    combo.set_names(["C", "B", "A"])
    assert combo.currentText() == "B"


def test_pick_combo_set_names_unchanged_is_noop(qapp):
    """Обновление тем же списком не пересоздаёт его — иначе открытый список закрывался бы."""
    combo = PickCombo("")
    combo.set_names(["A", "B"])
    seen = []
    combo.model().modelReset.connect(lambda: seen.append(1))
    combo.model().rowsRemoved.connect(lambda *_: seen.append(1))
    combo.set_names(["A", "B"])
    assert seen == []


# --- подписи и кнопки ---------------------------------------------------------------

def test_field_labels_say_task(window):
    from PySide6.QtWidgets import QLabel, QPushButton
    labels = {l.text() for l in window.findChildren(QLabel)}
    assert {"Задача", "Подзадача"} <= labels
    assert "Продукт" not in labels
    new_buttons = [b for b in window.findChildren(QPushButton) if b.text().strip() == "Новая"]
    assert len(new_buttons) == 2


def test_empty_fields_main_button(window):
    window._set_text(window.product, "")
    window._update_timer()
    assert window.main_btn.text().strip() == "Начать"
    assert "Выберите задачу" in window.hint.text()


# --- группировка списка -------------------------------------------------------------

def test_group_rows_order_and_totals():
    sessions = [  # как из work_sessions: идущая первой, дальше по последней работе
        {"id": 1, "product_id": 10, "product": "DAC", "subtask_id": 1, "subtask": "ИИ", "status": "active",
         "total": 7, "pair_total": 7},
        {"id": 2, "product_id": 20, "product": "Titan", "subtask_id": 2, "subtask": "Сборка", "status": "paused",
         "total": 1, "pair_total": 2221},  # прошлая завершённая сессия — 37 мин
        {"id": 3, "product_id": 10, "product": "DAC", "subtask_id": 3, "subtask": "Съемка", "status": "paused",
         "total": 100, "pair_total": 100},
        {"id": 5, "product_id": 10, "product": "DAC", "subtask_id": 3, "subtask": "Съемка", "status": "paused",
         "total": 30, "pair_total": 100},  # две открытые сессии одной подзадачи — считать один раз
        {"id": 4, "product_id": 30, "product": "Pulsar", "subtask_id": 4, "subtask": "Монтаж", "status": "stopped",
         "total": 50, "pair_total": 50},
    ]
    rows = TimerWindow._group_rows(sessions, {10: 500})
    shape = [(r.get("kind"), r.get("id") or r["product"]) for r in rows]
    assert shape == [("group", "DAC"), (None, 1), (None, 3), (None, 5),
                     ("group", "Titan"), (None, 2),
                     ("group", "Pulsar"), (None, 4)]
    dac, titan, pulsar = (r for r in rows if r.get("kind") == "group")
    assert dac["first"] and not titan["first"]
    assert dac["active"] and not titan["active"]
    assert dac["total"] == 107 and dac["tokens"] == 500
    assert titan["total"] == 2221  # всё время задачи, не только открытой сессии
    assert pulsar["total"] == 50  # завершённые подзадачи тоже считаются, пока задачу не сдали


def test_list_headers_not_selectable(window, db, pair):
    db.start(*pair("DAC 520SV", "Съемка"), at=at(10))
    db.pause_active(at=at(11))
    db.start(*pair("DAC 520SV", "Сбор материала"), at=at(11))
    window.reload()
    rows = list_rows(window)
    assert [r.get("kind") for r in rows] == ["group", None, None]
    header = window.list.item(0)
    assert not header.flags() & Qt.ItemIsSelectable
    assert window.list_title.text().startswith("Задач: 1  ·  подзадач: 2")


def test_click_header_sets_only_task(window, db, pair):
    db.start(*pair("DAC 520SV", "Съемка"), at=at(10))
    db.pause_active(at=at(11))
    window.reload()
    window._set_text(window.product, "")
    window._set_text(window.subtask, "Перевод")
    window._on_item_clicked(window.list.item(0))
    assert window.product.currentText() == "DAC 520SV"
    assert window.subtask.currentText() == "Перевод"


def test_renamed_running_task_updates_fields(window, db, pair):
    """Переименовали идущую задачу в Сводке — в полях новое имя, кнопка «Пауза», а не «Переключиться»
    на несуществующую (которая молча создала бы дубль). code-review 2.3.0."""
    p, s = pair("A", "Съемка")
    db.start(p, s)
    window.reload()
    assert window.product.currentText() == "A"
    db.rename_product(p, "A2")
    window.hub.changed.emit()
    assert window.product.currentText() == "A2"
    assert window.main_btn.text().strip() == "Пауза"
    assert window.product.findText("A") == -1


def test_archived_task_leaves_field_and_list(window, db, pair):
    """Задачу сдали в Сводке — поле очищается, открытый список не пересоздаётся на каждом обновлении."""
    p, s = pair("A", "Съемка")
    pair("B")
    window.reload()
    window._set_text(window.product, "A")
    db.set_archived(p, True)
    window.hub.changed.emit()
    assert window.product.currentText() == ""
    assert window.product.findText("A") == -1
    names = [window.product.itemText(i) for i in range(window.product.count())]
    assert names == db.product_names()  # без «призраков» — значит set_names дальше будет no-op


def test_click_row_sets_both_fields(window, db, pair):
    db.start(*pair("DAC 520SV", "Съемка"), at=at(10))
    db.pause_active(at=at(11))
    window.reload()
    window._on_item_clicked(window.list.item(1))
    assert (window.product.currentText(), window.subtask.currentText()) == ("DAC 520SV", "Съемка")
    assert window.main_btn.text().strip() == "Продолжить"


# --- Mac: выход по Cmd+Q / из Dock ------------------------------------------------------

@pytest.fixture
def mac_window(qapp, db, monkeypatch):
    from timetracker import theme
    monkeypatch.setattr(theme, "MAC", True)  # QuitGuard ставится только на Mac
    w = TimerWindow(db, Hub())
    yield w
    w._ticker.stop()
    w.deleteLater()


@pytest.mark.parametrize("answer", [True, False])
def test_mac_quit_request_pauses_hidden_timer(mac_window, db, pair, qapp, monkeypatch, answer):
    """Cmd+Q при спрятанном окне таймера (мини-окно, строка меню): Qt закрывает только видимые окна —
    таймер не вставал на паузу, при следующем запуске «закрылась некорректно» (Mac, 18.10.2026)."""
    from PySide6.QtCore import QEvent
    from timetracker import dialogs
    asked = []
    monkeypatch.setattr(dialogs, "ask", lambda *a, **k: asked.append(1) or answer)
    db.start(*pair("Монтаж"))
    mac_window.hide()
    qapp.sendEvent(qapp, QEvent(QEvent.Quit))
    assert asked  # идущий таймер — сначала спросить
    assert bool(db.active_session()) is not answer  # «Да» — пауза, «Нет» — таймер идёт дальше


def test_mac_minimize_keeps_window_in_dock(mac_window, qapp):
    """Mac: свёрнутое окно остаётся в Dock (не прячется) — иначе клик по нему в Dock открывал пустую
    рамку (18.10.2026). Развернули из Dock — мини-окно прячется."""
    from PySide6.QtCore import Qt
    mac_window.show()
    mac_window.setWindowState(Qt.WindowMinimized)
    qapp.processEvents()
    assert mac_window.mini.isVisible() and mac_window.isVisible()
    mac_window.setWindowState(Qt.WindowNoState)
    qapp.processEvents()
    assert not mac_window.mini.isVisible()
