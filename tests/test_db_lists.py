"""Список окна таймера (work_sessions), ручная правка времени, пересечения, итоги за период, копии базы."""
from datetime import datetime

from timetracker import db as dbm
from conftest import at


# --- work_sessions: «мои текущие задачи» ------------------------------------------

def test_work_sessions_active_first(db, pair):
    a = db.start(*pair("A"), at=at(10))
    db.pause_active(at=at(11))
    b = db.start(*pair("B"), at=at(9))  # раньше по времени, но идёт
    ids = [s["id"] for s in db.work_sessions(at=at(12))]
    assert ids[0] == b and a in ids


def test_work_sessions_keeps_last_finished_pair(db, pair):
    """Завершённая подзадача остаётся в списке (серой), пока задачу не сдали."""
    p, s = pair("A")
    sid = db.start(p, s, at=at(10))
    db.stop(sid, at=at(11))
    rows = db.work_sessions(at=at(12))
    assert [(r["id"], r["status"]) for r in rows] == [(sid, "stopped")]


def test_work_sessions_one_row_per_finished_pair(db, pair):
    p, s = pair("A")
    first = db.start(p, s, at=at(10))
    db.stop(first, at=at(11))
    second = db.start(p, s, at=at(12))
    db.stop(second, at=at(13))
    assert [r["id"] for r in db.work_sessions(at=at(14))] == [second]


def test_work_sessions_finished_hidden_when_pair_open(db, pair):
    p, s = pair("A")
    first = db.start(p, s, at=at(10))
    db.stop(first, at=at(11))
    second = db.start(p, s, at=at(12))
    assert [r["id"] for r in db.work_sessions(at=at(13))] == [second]


def test_work_sessions_archived_product_gone(db, pair):
    p, s = pair("A")
    db.start(p, s, at=at(10))
    db.set_archived(p, True, at=at(11))
    assert db.work_sessions(at=at(12)) == []


def test_work_sessions_total_counts_running_time(db, pair):
    db.start(*pair("A"), at=at(10))
    assert db.work_sessions(at=at(10, 30))[0]["total"] == 1800


def test_work_sessions_pair_total_includes_finished_sessions(db, pair):
    """Завершили подзадачу и начали снова — в списке всё время подзадачи, а не только новой сессии
    (TitanFlex показывал 00:00:01 вместо 37 мин, 2.3.0)."""
    p, s = pair("A")
    first = db.start(p, s, at=at(10))
    db.stop(first, at=at(11))
    db.start(p, s, at=at(12))
    other = pair("A", "Другая")
    db.start(*other, at=at(12, 10))  # другая подзадача той же задачи не смешивается
    rows = {r["subtask"]: r for r in db.work_sessions(at=at(12, 30))}
    assert rows["Without task"]["total"] == 600  # сама сессия: 12:00–12:10
    assert rows["Without task"]["pair_total"] == 3600 + 600
    assert rows["Другая"]["pair_total"] == 1200


def test_last_session(db, pair):
    db.start(*pair("A"), at=at(10))
    b = db.start(*pair("B"), at=at(11))
    db.pause_active(at=at(12))
    assert db.last_session()["id"] == b


# --- пересечения и ручная правка ----------------------------------------------------

def test_find_overlap(db, pair):
    sid = db.start(*pair("A"), at=at(10))
    db.pause_active(at=at(11))
    assert db.find_overlap(at(10, 30), at(12))["product"] == "A"
    assert db.find_overlap(at(11), at(12)) is None  # стык — не пересечение
    assert db.find_overlap(at(9), at(10)) is None
    interval_id = db.day_intervals(sid, at(0), at(0, day=1))[0]["id"]
    assert db.find_overlap(at(10, 30), at(12), exclude_ids=[interval_id]) is None


def test_add_manual_into_paused_session(db, pair):
    p, s = pair("A")
    sid = db.start(p, s, at=at(10))
    db.pause_active(at=at(11))
    assert db.add_manual(p, s, at(8), at(9)) == sid
    assert db.session_total(sid) == 2 * 3600


def test_add_manual_new_stopped_session(db, pair):
    p, s = pair("A")
    sid = db.add_manual(p, s, at(8), at(9))
    info = db.session_info(sid)
    assert info["status"] == "stopped"
    assert db.session_total(sid) == 3600


def test_save_session_edit_moves_and_edits(db, pair):
    a, s = pair("A")
    b, s2 = pair("B", "Съемка")
    sid = db.start(a, s, at=at(10))
    db.pause_active(at=at(11))
    iid = db.day_intervals(sid, at(0), at(0, day=1))[0]["id"]
    db.save_session_edit(sid, b, s2, [(iid, at(10), at(10, 30)), (None, at(12), at(12, 15))], [])
    info = db.session_info(sid)
    assert (info["product_id"], info["subtask_id"]) == (b, s2)
    assert db.session_total(sid) == 45 * 60


def test_save_session_edit_deletes_empty_session(db, pair):
    a, s = pair("A")
    sid = db.start(a, s, at=at(10))
    db.pause_active(at=at(11))
    iid = db.day_intervals(sid, at(0), at(0, day=1))[0]["id"]
    db.save_session_edit(sid, a, s, [], [iid])
    assert db.session_info(sid) is None


def test_session_days(db, pair):
    p, s = pair("A")
    sid = db.add_manual(p, s, at(10), at(11))
    db.add_manual(p, s, at(10, day=1), at(11, day=1))  # уходит в новую stopped-сессию
    assert db.session_days(sid) == 1


# --- итоги -------------------------------------------------------------------------

def test_total_between_clips_to_period(db, pair):
    p, s = pair("A")
    db.add_manual(p, s, at(23), at(1, day=1))  # через полночь
    assert db.total_between(at(0), at(0, day=1), at=at(12, day=1)) == 3600


def test_report_rows_clipped(db, pair):
    p, s = pair("A")
    db.add_manual(p, s, at(23), at(1, day=1))
    rows = db.report_rows(at(0, day=1), at(0, day=2), at=at(12, day=1))
    assert [(r["start"], r["end"]) for r in rows] == [(dbm.to_ts(at(0, day=1)), dbm.to_ts(at(1, day=1)))]


# --- копии базы ---------------------------------------------------------------------

def test_backup_once_a_day_and_force(db, monkeypatch):
    monkeypatch.setattr(dbm, "now", lambda: datetime(2026, 10, 14, 9, 0, 0))
    assert db.backup() is not None
    assert db.backup() is None  # второй раз за день — нет
    assert db.backup(force=True) is not None
    assert len(db.backups()) == 2


def test_backup_keeps_last_n(db, monkeypatch):
    for i in range(dbm.BACKUP_KEEP + 3):
        monkeypatch.setattr(dbm, "now", lambda i=i: datetime(2026, 10, 1 + i, 9, 0, 0))
        db.backup()
    names = [p.rsplit("timetracker-", 1)[1] for p in db.backups()]
    assert len(names) == dbm.BACKUP_KEEP
    assert names[0].startswith("2026-10-17")  # самые новые остаются
