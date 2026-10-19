"""Задачи (в коде — products), подзадачи, «сдана», переименование/объединение/удаление, токены."""
import pytest

from conftest import at


# --- имена ------------------------------------------------------------------

def test_find_product_ignores_case_cyrillic(db):
    """SQLite NOCASE не понимает кириллицу — сравнение через casefold в Python."""
    pid = db.get_or_create_product("Монтаж Ролика")
    assert db.find_product("монтаж ролика") == pid
    assert db.get_or_create_product("  МОНТАЖ РОЛИКА ") == pid


def test_product_names_recent_first(db, pair):
    a, s = pair("A")
    b, _ = pair("B")
    db.start(a, s, at=at(10))
    db.start(b, s, at=at(11))
    assert db.product_names()[:2] == ["B", "A"]


def test_new_base_is_empty(db):
    """Новая база: ни задач, ни готовых подзадач — только служебная «Without task» (2.4.1)."""
    assert db.subtask_names() == ["Without task"]
    assert db.product_names(include_archived=True) == []


def test_rename_subtask_everywhere(db, pair):
    """Опечатку в подзадаче исправляют переименованием: сессии те же, имя новое везде."""
    p, s = pair("A", "Мотнаж")
    sid = db.start(p, s, at=at(10))
    db.set_setting("last_subtask", "Мотнаж")
    db.rename_subtask(s, "Монтаж")
    assert db.find_subtask("Монтаж") == s and db.find_subtask("Мотнаж") is None
    assert db.active_session()["id"] == sid and db.active_session()["subtask"] == "Монтаж"
    assert db.get_setting("last_subtask") == "Монтаж"
    db.rename_subtask(s, "монтаж")  # только регистр — не «уже есть»
    assert db.subtask_names()[-1] == "монтаж"


def test_rename_subtask_into_existing_merges(db, pair):
    p, typo = pair("A", "Мотнаж")
    db.start(p, typo, at=at(10))
    db.pause_active(at=at(11))
    right = db.create_subtask("Монтаж")
    with pytest.raises(ValueError):
        db.rename_subtask(typo, "МОНТАЖ")
    db.merge_subtasks(typo, right)
    assert db.find_subtask("Мотнаж") is None
    assert db.work_sessions(at=at(12))[0]["subtask"] == "Монтаж"
    assert db.work_sessions(at=at(12))[0]["pair_total"] == 3600


def test_delete_pair_removes_all_its_time(db, pair):
    """ПКМ «Удалить подзадачу» в окне таймера: всё время пары (все сессии) уходит; другие пары
    и та же подзадача в другой задаче — остаются; имя подзадачи остаётся, только пока где-то используется."""
    a, s = pair("A", "Монтаж")
    b, _ = pair("B", "Монтаж")
    _, other = pair("A", "Титры")
    db.start(a, s, at=at(9)); db.stop(db.active_session()["id"], at=at(10))
    db.start(a, s, at=at(11))  # вторая сессия той же пары, идёт
    db.start(b, s, at=at(12)); db.start(a, other, at=at(13)); db.pause_active(at=at(14))
    db.delete_pair(a, s)
    pairs = {(r["product"], r["subtask"]) for r in db.work_sessions(at=at(15))}
    assert pairs == {("B", "Монтаж"), ("A", "Титры")}
    assert db.find_subtask("Монтаж") == s  # ещё есть в задаче B
    db.delete_pair(b, s)
    assert db.find_subtask("Монтаж") is None
    default = db.find_subtask("Without task")
    db.start(a, default, at=at(15)); db.delete_pair(a, default)
    assert db.find_subtask("Without task") == default


def test_without_task_cannot_be_renamed(db):
    default = db.find_subtask("Without task")
    with pytest.raises(ValueError):
        db.rename_subtask(default, "Другое")
    with pytest.raises(ValueError):
        db.merge_subtasks(default, db.create_subtask("Другое"))


def test_create_subtask_reuses_existing(db):
    assert db.create_subtask("съемка") == db.create_subtask("Съемка")


def test_delete_subtask_rules(db, pair):
    with pytest.raises(ValueError):
        db.delete_subtask("Without task")
    p, s = pair("A", "Съемка")
    db.start(p, s, at=at(10))
    with pytest.raises(ValueError):
        db.delete_subtask("Съемка")
    db.create_subtask("Лишняя")
    db.delete_subtask("Лишняя")
    assert db.find_subtask("Лишняя") is None


# --- «сдана» -----------------------------------------------------------------

def test_archive_stops_open_sessions_and_hides(db, pair):
    p, s = pair("A")
    sid = db.start(p, s, at=at(10))
    assert db.open_session_count(p) == 1
    db.set_archived(p, True, at=at(11))
    assert db.session_info(sid)["status"] == "stopped"
    assert "A" not in db.product_names()
    assert "A" in db.product_names(include_archived=True)
    db.set_archived(p, False)
    assert "A" in db.product_names()


# --- переименование / объединение / удаление ------------------------------------

def test_rename_conflict(db):
    a = db.get_or_create_product("A")
    db.get_or_create_product("B")
    with pytest.raises(ValueError):
        db.rename_product(a, "b")
    db.rename_product(a, "A2")
    assert db.find_product("A2") == a


def test_merge_moves_sessions_and_tokens(db, pair):
    a, s = pair("A")
    b, _ = pair("B")
    sid = db.start(a, s, at=at(10))
    db.add_tokens(a, "ElevenLabs", 100)
    db.merge_products(a, b)
    assert db.find_product("A") is None
    assert db.session_info(sid)["product_id"] == b
    assert db.product_tokens(b) == 100


def test_delete_product_removes_everything(db, pair):
    a, s = pair("A")
    db.start(a, s, at=at(10))
    db.add_tokens(a, "X", 5)
    db.delete_product(a)
    assert db.find_product("A") is None
    assert db.token_totals() == {}
    assert db.work_sessions(at=at(11)) == []


# --- токены ------------------------------------------------------------------

def test_add_tokens_keeps_existing_model_spelling(db):
    p = db.get_or_create_product("A")
    db.add_tokens(p, "ElevenLabs", 100, at=at(10))
    db.add_tokens(p, "  elevenlabs ", 50, at=at(11))
    assert db.model_names() == ["ElevenLabs"]
    assert db.product_tokens(p) == 150


def test_token_totals_and_history(db):
    a = db.get_or_create_product("A")
    b = db.get_or_create_product("B")
    db.add_tokens(a, "X", 10, at=at(10))
    first = db.add_tokens(a, "X", 20, at=at(11))
    db.add_tokens(b, "Y", 5, at=at(12))
    assert db.token_totals() == {a: 30, b: 5}
    assert [h["tokens"] for h in db.token_history(a)] == [20, 10]  # новые сверху
    db.delete_tokens(first)
    assert db.product_tokens(a) == 10


def test_token_rows_period(db):
    a = db.get_or_create_product("A")
    db.add_tokens(a, "X", 1, at=at(10))
    db.add_tokens(a, "X", 2, at=at(10, day=1))
    assert [r["tokens"] for r in db.token_rows(at(0), at(0, day=1))] == [1]
