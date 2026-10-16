"""Report data shaping (no UI): periods, per-product tree, per-day journal, CSV export."""
import csv
from datetime import datetime, time as dtime, timedelta

from . import db as dbm

LAST_30 = "Последние 30 дней"
ALL_TIME = "Всё время"
PERIODS = ["Сегодня", "Вчера", "Эта неделя", "Прошлая неделя", "Этот месяц", "Прошлый месяц", LAST_30, ALL_TIME]


def period_bounds(name, today):
    day = datetime.combine(today, dtime())
    if name == "Сегодня":
        return day, day + timedelta(days=1)
    if name == "Вчера":
        return day - timedelta(days=1), day
    week = day - timedelta(days=today.weekday())
    if name == "Эта неделя":
        return week, week + timedelta(days=7)
    if name == "Прошлая неделя":
        return week - timedelta(days=7), week
    month = day.replace(day=1)
    next_month = (month + timedelta(days=32)).replace(day=1)
    if name == "Этот месяц":
        return month, next_month
    if name == "Прошлый месяц":
        return (month - timedelta(days=1)).replace(day=1), month
    if name == LAST_30:
        return day - timedelta(days=29), day + timedelta(days=1)
    return datetime(1970, 1, 1), datetime(9999, 12, 31)


def hours(seconds):
    return f"{seconds / 3600:.2f}"


def minutes(seconds):
    """Whole minutes: 1 h 26 min -> '86'."""
    return str(int(round(seconds / 60)))


def filter_rows(rows, query, field="subtask"):
    """Rows whose product or `field` (subtask for time, model for tokens) contains the query."""
    query = query.strip().casefold()
    if not query:
        return rows
    return [r for r in rows if query in r["product"].casefold() or query in r[field].casefold()]


def _seconds(start, end):
    return max(0.0, (end - start).total_seconds())


def aggregate(rows):
    """Interval rows -> {product_id: {name, total, last, subtasks: {subtask_id: {..., sessions: {...}}}}}."""
    products = {}
    for row in rows:
        start, end = dbm.from_ts(row["start"]), dbm.from_ts(row["end"])
        seconds = _seconds(start, end)
        product = products.setdefault(
            row["product_id"], {"name": row["product"], "total": 0, "last": end, "subtasks": {}}
        )
        subtask = product["subtasks"].setdefault(
            row["subtask_id"], {"name": row["subtask"], "total": 0, "last": end, "sessions": {}}
        )
        session = subtask["sessions"].setdefault(
            row["id"], {"total": 0, "first": start, "last": end, "status": row["status"], "days": {}}
        )
        for node in (product, subtask, session):
            node["total"] += seconds
            node["last"] = max(node["last"], end)
        session["first"] = min(session["first"], start)
        session["days"][start.date()] = session["days"].get(start.date(), 0) + seconds
    return products


def aggregate_tokens(rows):
    """Token rows -> {product_id: {name, total, last, models: {model: {total, last, entries: [...]}}}}."""
    products = {}
    for row in rows:
        at = dbm.from_ts(row["created_at"])
        product = products.setdefault(row["product_id"], {"name": row["product"], "total": 0, "last": at, "models": {}})
        model = product["models"].setdefault(row["model"], {"total": 0, "last": at, "entries": []})
        for node in (product, model):
            node["total"] += row["tokens"]
            node["last"] = max(node["last"], at)
        model["entries"].append({"id": row["id"], "tokens": row["tokens"], "at": at})
    return products


def split_by_day(start, end):
    while start.date() < end.date():
        midnight = datetime.combine(start.date() + timedelta(days=1), dtime())
        yield start, midnight
        start = midnight
    if end > start:
        yield start, end


def build_days(rows):
    """Interval rows -> list of days (newest first), each with its entries (one per session)."""
    days = {}
    for row in rows:
        for start, end in split_by_day(dbm.from_ts(row["start"]), dbm.from_ts(row["end"])):
            day = days.setdefault(start.date(), {"date": start.date(), "total": 0, "entries": {}})
            entry = day["entries"].setdefault(row["id"], {
                "session_id": row["id"], "product_id": row["product_id"], "product": row["product"],
                "subtask_id": row["subtask_id"], "subtask": row["subtask"], "status": row["status"],
                "seconds": 0, "intervals": [],
            })
            seconds = _seconds(start, end)
            entry["seconds"] += seconds
            entry["intervals"].append((start, end))
            day["total"] += seconds
    result = []
    for day in sorted(days.values(), key=lambda d: d["date"], reverse=True):
        day["entries"] = sorted(day["entries"].values(), key=lambda e: e["intervals"][-1][1], reverse=True)
        result.append(day)
    return result


def write_csv(path, rows):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["Задача", "Подзадача", "Сессия", "Дата", "Начало", "Конец", "Длительность", "Часы"])
        for row in rows:
            start, end = dbm.from_ts(row["start"]), dbm.from_ts(row["end"])
            seconds = _seconds(start, end)
            writer.writerow([
                row["product"], row["subtask"], row["id"], f"{start:%d.%m.%Y}", f"{start:%H:%M:%S}",
                f"{end:%H:%M:%S}", dbm.fmt_duration(seconds), hours(seconds).replace(".", ","),
            ])
