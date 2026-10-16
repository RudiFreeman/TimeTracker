"""Таймер в базе: старт / пауза / продолжить / завершить, авто-пауза по лимиту дня, восстановление после сбоя."""
from conftest import at


def status(db, session_id):
    return db.session_info(session_id)["status"]


# --- start / pause / resume / stop ------------------------------------------

def test_start_creates_active_session(db, pair):
    p, s = pair("DAC 520SV", "Съемка")
    sid = db.start(p, s, at=at(10))
    assert status(db, sid) == "active"
    assert db.active_session()["id"] == sid


def test_only_one_session_runs(db, pair):
    a = db.start(*pair("A"), at=at(10))
    b = db.start(*pair("B"), at=at(11))
    assert status(db, a) == "paused"
    assert status(db, b) == "active"
    assert db.session_total(a, at=at(12)) == 3600  # первая встала на паузу ровно в момент старта второй


def test_start_same_pair_resumes_paused_session(db, pair):
    p, s = pair("A", "Съемка")
    first = db.start(p, s, at=at(10))
    db.pause_active(at=at(10, 30))
    again = db.start(p, s, at=at(11))
    assert again == first
    assert db.session_total(first, at=at(11, 30)) == 3600


def test_stopped_session_is_not_reopened(db, pair):
    """PRD: возврат к задаче после «Завершить» — новая сессия."""
    p, s = pair("A")
    first = db.start(p, s, at=at(10))
    db.stop(first, at=at(11))
    second = db.start(p, s, at=at(12))
    assert second != first
    assert status(db, first) == "stopped"


def test_resume_only_paused(db, pair):
    sid = db.start(*pair("A"), at=at(10))
    assert db.resume(sid, at=at(10, 5)) is False  # уже идёт
    db.stop(sid, at=at(11))
    assert db.resume(sid, at=at(12)) is False  # завершённую не продолжить
    assert status(db, sid) == "stopped"


def test_stop_closes_open_interval(db, pair):
    sid = db.start(*pair("A"), at=at(10))
    db.stop(sid, at=at(10, 45))
    assert db.active_session() is None
    assert db.session_total(sid, at=at(18)) == 45 * 60


def test_start_unarchives_product(db, pair):
    p, s = pair("A")
    db.set_archived(p, True)
    assert "A" not in db.product_names()
    db.start(p, s, at=at(10))
    assert "A" in db.product_names()


# --- лимит дня и авто-пауза ---------------------------------------------------

def test_deadline_is_day_limit(db):
    assert db.deadline_for(at(10), after_hours=False) == at(18)


def test_deadline_after_hours_is_end_of_day(db):
    assert db.deadline_for(at(19), after_hours=True) == at(23, 59, 59)


def test_deadline_started_after_limit_is_end_of_day(db):
    """Запущено после 18:00 — авто-пауза в 23:59:59, а не «в прошлом»."""
    assert db.deadline_for(at(18, 30), after_hours=False) == at(23, 59, 59)


def test_no_deadline_when_limit_disabled(db):
    db.set_setting("limit_enabled", "0")
    assert db.deadline_for(at(10), after_hours=False) is None
    assert db.is_after_limit(at(20)) is False


def test_custom_limit_and_after_limit(db):
    db.set_setting("limit_time", "17:30")
    assert db.deadline_for(at(10), False) == at(17, 30)
    assert db.is_after_limit(at(17, 29)) is False
    assert db.is_after_limit(at(17, 30)) is True


def test_bad_limit_setting_falls_back_to_default(db):
    db.set_setting("limit_time", "мусор")
    assert db.limit_config()[1].hour == 18


def test_active_session_has_deadline(db, pair):
    db.start(*pair("A"), at=at(10))
    assert db.active_session()["deadline"] == at(18)


# --- восстановление после сбоя --------------------------------------------------

def test_recover_closes_at_last_heartbeat(db, pair):
    sid = db.start(*pair("A"), at=at(10))
    db.heartbeat(at=at(10, 20))
    assert db.recover() == 1
    assert status(db, sid) == "paused"
    assert db.session_total(sid, at=at(23)) == 20 * 60


def test_recover_caps_at_deadline(db, pair):
    """Компьютер не выключили, программа «жила» до 21:00 — засчитывается только до 18:00."""
    sid = db.start(*pair("A"), at=at(17))
    db.heartbeat(at=at(21))
    db.recover()
    assert db.session_total(sid, at=at(23)) == 3600


def test_recover_nothing_open(db, pair):
    sid = db.start(*pair("A"), at=at(10))
    db.pause_active(at=at(11))
    assert db.recover() == 0
    assert db.session_total(sid, at=at(23)) == 3600
