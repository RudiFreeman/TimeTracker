"""Отчёты без UI: периоды, разбивка по дням, сводка, CSV, форматирование."""
import csv
from datetime import date, datetime

from timetracker import db as dbm
from timetracker import reporting, theme
from conftest import at


def test_period_bounds_week_starts_monday():
    start, end = reporting.period_bounds("Эта неделя", date(2026, 10, 14))  # среда
    assert start == datetime(2026, 10, 12) and end == datetime(2026, 10, 19)


def test_period_bounds_months():
    assert reporting.period_bounds("Прошлый месяц", date(2026, 1, 10)) == (datetime(2025, 12, 1), datetime(2026, 1, 1))
    assert reporting.period_bounds("Этот месяц", date(2026, 12, 31)) == (datetime(2026, 12, 1), datetime(2027, 1, 1))


def test_period_bounds_today_yesterday():
    today = date(2026, 10, 14)
    assert reporting.period_bounds("Сегодня", today) == (datetime(2026, 10, 14), datetime(2026, 10, 15))
    assert reporting.period_bounds("Вчера", today) == (datetime(2026, 10, 13), datetime(2026, 10, 14))


def test_split_by_day_over_midnight():
    parts = list(reporting.split_by_day(at(23), at(1, day=1)))
    assert parts == [(at(23), at(0, day=1)), (at(0, day=1), at(1, day=1))]


def test_hours_minutes():
    assert reporting.minutes(86 * 60) == "86"
    assert reporting.hours(5400) == "1.50"


def test_formatters():
    assert dbm.fmt_duration(3661) == "01:01:01"
    assert dbm.fmt_duration(-5) == "00:00:00"
    assert theme.fmt_human(5160) == "1 ч 26 мин"
    assert theme.fmt_tokens(1234567) == "1 234 567"  # неразрывные пробелы — число не переносится


def _rows(db, pair):
    p, s = pair("DAC 520SV", "Съемка")
    db.add_manual(p, s, at(10), at(11))
    db.add_manual(p, s, at(23), at(1, day=1))
    return db.report_rows(at(0), at(0, day=2), at=at(12, day=1))


def test_build_days_newest_first(db, pair):
    days = reporting.build_days(_rows(db, pair))
    assert [d["date"] for d in days] == [date(2026, 10, 15), date(2026, 10, 14)]
    assert days[1]["total"] == 2 * 3600  # 10–11 и 23–24


def test_aggregate_tree(db, pair):
    tree = reporting.aggregate(_rows(db, pair))
    (product,) = tree.values()
    assert product["name"] == "DAC 520SV" and product["total"] == 3 * 3600
    (subtask,) = product["subtasks"].values()
    assert subtask["name"] == "Съемка"


def test_filter_rows(db, pair):
    rows = _rows(db, pair)
    assert reporting.filter_rows(rows, "съем") == rows
    assert reporting.filter_rows(rows, "dac") == rows
    assert reporting.filter_rows(rows, "нет такого") == []


def test_write_csv(db, pair, tmp_path):
    path = tmp_path / "out.csv"
    reporting.write_csv(str(path), _rows(db, pair))
    with open(path, encoding="utf-8-sig", newline="") as f:
        lines = list(csv.reader(f, delimiter=";"))
    assert lines[0][:2] == ["Задача", "Подзадача"]
    assert lines[1][0] == "DAC 520SV"
    assert lines[1][-1] == "1,00"  # десятичная запятая для Excel
