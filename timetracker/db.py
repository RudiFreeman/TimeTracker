"""SQLite storage: products, subtasks, sessions and the time intervals inside them.

Product  -> global entity ("Товар А").
Subtask  -> kind of work ("Перевод").
Session  -> one iteration of work on a product + subtask. A session collects one or
            more intervals (each Play..Pause stretch). Stopped sessions are never
            reopened: coming back to a product starts a new session.
Tokens   -> AI service usage (model + count, e.g. ElevenLabs) logged against a product.
"""
import os
import sqlite3
import sys
from datetime import datetime, time as dtime

TS_FMT = "%Y-%m-%d %H:%M:%S"
DB_FILENAME = "timetracker.db"
BACKUP_DIR = "backups"
BACKUP_KEEP = 14
DEFAULT_SUBTASK = "Without task"
DEFAULT_SUBTASKS = [DEFAULT_SUBTASK, "Отбор материала", "Черновая сборка", "Написание текста", "Перевод"]
DEFAULT_SETTINGS = {"limit_enabled": "1", "limit_time": "18:00", "day_start": "09:00", "topmost": "1", "position": "",
                    "last_product": "", "last_subtask": ""}
END_OF_DAY = dtime(23, 59, 59)

SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    archived   INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS subtasks (
    id         INTEGER PRIMARY KEY,
    name       TEXT NOT NULL UNIQUE,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
    id         INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    subtask_id INTEGER NOT NULL REFERENCES subtasks(id),
    status     TEXT NOT NULL CHECK (status IN ('active', 'paused', 'stopped')),
    created_at TEXT NOT NULL,
    stopped_at TEXT
);
CREATE TABLE IF NOT EXISTS intervals (
    id          INTEGER PRIMARY KEY,
    session_id  INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    start       TEXT NOT NULL,
    end         TEXT,
    last_seen   TEXT,
    after_hours INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS token_usage (
    id         INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    tokens     INTEGER NOT NULL CHECK (tokens > 0),
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);
CREATE INDEX IF NOT EXISTS idx_intervals_session ON intervals(session_id);
CREATE INDEX IF NOT EXISTS idx_intervals_start ON intervals(start);
CREATE INDEX IF NOT EXISTS idx_tokens_created ON token_usage(created_at);
"""

SESSION_COLUMNS = """
    s.id, s.status, s.product_id, s.subtask_id, p.name AS product, t.name AS subtask
"""
SESSION_JOINS = """
    FROM sessions s
    JOIN products p ON p.id = s.product_id
    JOIN subtasks t ON t.id = s.subtask_id
"""
# Seconds between two timestamp strings, rounded to whole seconds.
SECONDS = "ROUND((julianday({end}) - julianday({start})) * 86400)"


def app_dir():
    """Folder next to the .exe (or the project root when run from source)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def now():
    return datetime.now().replace(microsecond=0)


def to_ts(dt):
    return dt.strftime(TS_FMT)


def from_ts(text):
    return datetime.strptime(text, TS_FMT) if text else None


def fmt_duration(seconds):
    seconds = int(max(0, round(seconds)))
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_hhmm(text):
    """'18:00' -> time(18, 0). Raises ValueError on bad input."""
    return datetime.strptime(text.strip(), "%H:%M").time()


class Database:
    def __init__(self, path=None):
        self.path = path or os.path.join(app_dir(), DB_FILENAME)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.executescript(SCHEMA)
        self._migrate()
        with self.conn:
            if not self.conn.execute("SELECT 1 FROM subtasks LIMIT 1").fetchone():
                stamp = to_ts(now())
                self.conn.executemany(
                    "INSERT INTO subtasks (name, sort_order, created_at) VALUES (?, ?, ?)",
                    [(name, order, stamp) for order, name in enumerate(DEFAULT_SUBTASKS)],
                )
            self.conn.executemany(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", DEFAULT_SETTINGS.items()
            )

    def close(self):
        self.conn.close()

    # ------------------------------------------------------------------ backups

    def backup_dir(self):
        return os.path.join(os.path.dirname(os.path.abspath(self.path)), BACKUP_DIR)

    def backups(self):
        """Backup file paths, newest first (names start with the date, so they sort by time)."""
        folder = self.backup_dir()
        if not os.path.isdir(folder):
            return []
        names = [n for n in os.listdir(folder) if n.startswith("timetracker-") and n.endswith(".db")]
        return [os.path.join(folder, n) for n in sorted(names, reverse=True)]

    def backup(self, force=False):
        """Copy the database to backups/ — once a day, or right now with `force`.
        Keeps the newest BACKUP_KEEP copies. Returns the new file or None."""
        folder = self.backup_dir()
        os.makedirs(folder, exist_ok=True)
        stamp = now()
        name = f"timetracker-{stamp:%Y-%m-%d_%H-%M-%S}.db" if force else f"timetracker-{stamp:%Y-%m-%d}.db"
        target = os.path.join(folder, name)
        if not force and any(os.path.basename(p).startswith(f"timetracker-{stamp:%Y-%m-%d}") for p in self.backups()):
            return None
        dest = sqlite3.connect(target)
        try:
            self.conn.backup(dest)  # consistent copy even while the app is writing
        finally:
            dest.close()
        for old in self.backups()[BACKUP_KEEP:]:
            os.remove(old)
        return target

    def _migrate(self):
        """Columns added after the first release (CREATE TABLE IF NOT EXISTS won't add them)."""
        columns = {row["name"] for row in self.conn.execute("PRAGMA table_info(products)")}
        if "archived" not in columns:
            with self.conn:
                self.conn.execute("ALTER TABLE products ADD COLUMN archived INTEGER NOT NULL DEFAULT 0")

    # ----------------------------------------------------------------- settings

    def get_setting(self, key):
        row = self.conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else DEFAULT_SETTINGS.get(key, "")

    def set_setting(self, key, value):
        with self.conn:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def limit_config(self):
        """(enabled, time) of the end-of-day auto-pause."""
        enabled = self.get_setting("limit_enabled") == "1"
        try:
            limit = parse_hhmm(self.get_setting("limit_time"))
        except ValueError:
            limit = parse_hhmm(DEFAULT_SETTINGS["limit_time"])
        return enabled, limit

    def workday(self):
        """(start, end) of the working day: start from settings, end = the auto-pause time."""
        try:
            start = parse_hhmm(self.get_setting("day_start"))
        except ValueError:
            start = parse_hhmm(DEFAULT_SETTINGS["day_start"])
        return start, self.limit_config()[1]

    def is_after_limit(self, at):
        enabled, limit = self.limit_config()
        return enabled and at >= datetime.combine(at.date(), limit)

    def deadline_for(self, start, after_hours):
        """Moment an interval started at `start` must be auto-paused, or None.

        Normal intervals stop at the daily limit. Intervals the user deliberately
        started after the limit run until the end of that day.
        """
        enabled, limit = self.limit_config()
        if not enabled:
            return None
        day_limit = datetime.combine(start.date(), limit)
        if start < day_limit and not after_hours:
            return day_limit
        return datetime.combine(start.date(), END_OF_DAY)

    # ----------------------------------------------------- products & subtasks

    def _find_id(self, table, name):
        key = name.strip().casefold()  # SQLite NOCASE only folds ASCII, so match in Python
        for row in self.conn.execute(f"SELECT id, name FROM {table}"):
            if row["name"].casefold() == key:
                return row["id"]
        return None

    def product_names(self, include_archived=False):
        """Products, most recently worked on first; finished («сдан») ones only on request."""
        rows = self.conn.execute(
            f"""SELECT p.name, MAX(s.created_at) AS last_used
               FROM products p LEFT JOIN sessions s ON s.product_id = p.id
               {"" if include_archived else "WHERE p.archived = 0"}
               GROUP BY p.id
               ORDER BY last_used IS NULL, last_used DESC, p.name"""
        )
        return [row["name"] for row in rows]

    def archived_ids(self):
        return {row[0] for row in self.conn.execute("SELECT id FROM products WHERE archived = 1")}

    def set_archived(self, product_id, archived, at=None):
        """Mark a product finished (also finishing its open sessions) or back in work."""
        if archived:
            for row in self.conn.execute(
                "SELECT id FROM sessions WHERE product_id = ? AND status != 'stopped'", (product_id,)
            ).fetchall():
                self.stop(row["id"], at)
        with self.conn:
            self.conn.execute("UPDATE products SET archived = ? WHERE id = ?", (int(archived), product_id))

    def open_session_count(self, product_id):
        row = self.conn.execute(
            "SELECT COUNT(*) FROM sessions WHERE product_id = ? AND status != 'stopped'", (product_id,)
        ).fetchone()
        return row[0]

    def find_product(self, name):
        return self._find_id("products", name)

    def get_or_create_product(self, name):
        product_id = self.find_product(name)
        if product_id is None:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO products (name, created_at) VALUES (?, ?)", (name.strip(), to_ts(now()))
                )
            product_id = cur.lastrowid
        return product_id

    def rename_product(self, product_id, new_name):
        """Rename; raises ValueError if another product already has that name."""
        other = self.find_product(new_name)
        if other is not None and other != product_id:
            raise ValueError("exists")
        with self.conn:
            self.conn.execute("UPDATE products SET name = ? WHERE id = ?", (new_name.strip(), product_id))

    def merge_products(self, source_id, target_id):
        """Move all sessions of `source_id` to `target_id` and delete the source."""
        with self.conn:
            self.conn.execute("UPDATE sessions SET product_id = ? WHERE product_id = ?", (target_id, source_id))
            self.conn.execute("UPDATE token_usage SET product_id = ? WHERE product_id = ?", (target_id, source_id))
            self.conn.execute("DELETE FROM products WHERE id = ?", (source_id,))

    def delete_product(self, product_id):
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE product_id = ?", (product_id,))
            self.conn.execute("DELETE FROM token_usage WHERE product_id = ?", (product_id,))
            self.conn.execute("DELETE FROM products WHERE id = ?", (product_id,))

    def subtask_names(self):
        return [row["name"] for row in self.conn.execute("SELECT name FROM subtasks ORDER BY sort_order, id")]

    def find_subtask(self, name):
        return self._find_id("subtasks", name)

    def create_subtask(self, name):
        subtask_id = self.find_subtask(name)
        if subtask_id is None:
            with self.conn:
                cur = self.conn.execute(
                    "INSERT INTO subtasks (name, sort_order, created_at) "
                    "VALUES (?, (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM subtasks), ?)",
                    (name.strip(), to_ts(now())),
                )
            subtask_id = cur.lastrowid
        return subtask_id

    def delete_subtask(self, name):
        """Delete an unused custom subtask; raises ValueError explaining why not."""
        subtask_id = self.find_subtask(name)
        if subtask_id is None:
            return
        if name.strip().casefold() == DEFAULT_SUBTASK.casefold():
            raise ValueError(f"«{DEFAULT_SUBTASK}» — служебная подзадача, её нельзя удалить.")
        if self.conn.execute("SELECT 1 FROM sessions WHERE subtask_id = ? LIMIT 1", (subtask_id,)).fetchone():
            raise ValueError(f"По подзадаче «{name}» уже есть сессии — её нельзя удалить.")
        with self.conn:
            self.conn.execute("DELETE FROM subtasks WHERE id = ?", (subtask_id,))

    # -------------------------------------------------------------------- tokens

    def model_names(self):
        """Models used so far, most recently used first."""
        rows = self.conn.execute("SELECT model FROM token_usage GROUP BY model ORDER BY MAX(created_at) DESC, model")
        return [row["model"] for row in rows]

    def add_tokens(self, product_id, model, tokens, at=None):
        """Log `tokens` used with `model` for a product. A model typed in another case
        is stored under its existing spelling, so reports don't split it in two."""
        key = model.strip().casefold()
        model = next((name for name in self.model_names() if name.casefold() == key), model.strip())
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO token_usage (product_id, model, tokens, created_at) VALUES (?, ?, ?, ?)",
                (product_id, model, int(tokens), to_ts(at or now())),
            )
        return cur.lastrowid

    def product_tokens(self, product_id):
        row = self.conn.execute(
            "SELECT COALESCE(SUM(tokens), 0) FROM token_usage WHERE product_id = ?", (product_id,)
        ).fetchone()
        return row[0]

    def token_history(self, product_id):
        """All token records of a product, newest first."""
        rows = self.conn.execute(
            "SELECT id, model, tokens, created_at FROM token_usage WHERE product_id = ? ORDER BY created_at DESC, id DESC",
            (product_id,),
        )
        return [dict(row) for row in rows]

    def token_totals(self):
        """{product_id: tokens} over all time."""
        rows = self.conn.execute("SELECT product_id, SUM(tokens) FROM token_usage GROUP BY product_id")
        return {row[0]: row[1] for row in rows}

    def delete_tokens(self, usage_id):
        with self.conn:
            self.conn.execute("DELETE FROM token_usage WHERE id = ?", (usage_id,))

    def token_rows(self, start, end):
        """Token records logged within [start, end), oldest first."""
        rows = self.conn.execute(
            """SELECT u.id, u.product_id, p.name AS product, u.model, u.tokens, u.created_at
               FROM token_usage u JOIN products p ON p.id = u.product_id
               WHERE u.created_at >= ? AND u.created_at < ?
               ORDER BY u.created_at, u.id""",
            (to_ts(start), to_ts(end)),
        )
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------ sessions

    def active_session(self):
        """The running session with its open interval and auto-pause deadline, or None."""
        row = self.conn.execute(
            f"""SELECT {SESSION_COLUMNS}, i.start, i.after_hours
                {SESSION_JOINS}
                JOIN intervals i ON i.session_id = s.id AND i.end IS NULL
                WHERE s.status = 'active'
                LIMIT 1"""
        ).fetchone()
        if row is None:
            return None
        session = dict(row)
        session["start"] = from_ts(session["start"])
        session["deadline"] = self.deadline_for(session["start"], session["after_hours"])
        return session

    def last_session(self):
        """The session worked on most recently (any status), or None."""
        row = self.conn.execute(
            f"""SELECT {SESSION_COLUMNS}
                {SESSION_JOINS}
                LEFT JOIN intervals i ON i.session_id = s.id
                GROUP BY s.id
                ORDER BY MAX(COALESCE(i.end, i.start, s.created_at)) DESC, s.id DESC
                LIMIT 1"""
        ).fetchone()
        return dict(row) if row else None

    def open_sessions(self, at=None):
        """Active and paused sessions with their total time; active first, then most recent."""
        rows = self.conn.execute(
            f"""SELECT {SESSION_COLUMNS},
                       COALESCE(SUM({SECONDS.format(start="i.start", end="COALESCE(i.end, :now)")}), 0) AS total,
                       COALESCE(MAX(COALESCE(i.end, :now)), s.created_at) AS last_activity
                {SESSION_JOINS}
                LEFT JOIN intervals i ON i.session_id = s.id
                WHERE s.status != 'stopped'
                GROUP BY s.id
                ORDER BY s.status = 'active' DESC, last_activity DESC, s.id DESC""",
            {"now": to_ts(at or now())},
        )
        return [dict(row) for row in rows]

    def work_sessions(self, at=None):
        """The timer window's list: open sessions plus, for every product not yet handed over
        («сдан»), the last finished session of each product+subtask that has nothing open.
        Active first, then by last activity. ``total`` is the session's own time, ``pair_total`` —
        all sessions of its product+subtask (what the list shows)."""
        at = at or now()
        rows = self.conn.execute(
            f"""SELECT {SESSION_COLUMNS},
                       COALESCE(SUM({SECONDS.format(start="i.start", end="COALESCE(i.end, :now)")}), 0) AS total,
                       COALESCE(MAX(COALESCE(i.end, :now)), s.created_at) AS last_activity,
                       (SELECT COALESCE(SUM({SECONDS.format(start="j.start", end="COALESCE(j.end, :now)")}), 0)
                          FROM intervals j JOIN sessions y ON y.id = j.session_id
                         WHERE y.product_id = s.product_id AND y.subtask_id = s.subtask_id) AS pair_total
                {SESSION_JOINS}
                LEFT JOIN intervals i ON i.session_id = s.id
                WHERE s.status != 'stopped'
                   OR (p.archived = 0
                       AND s.id = (SELECT MAX(id) FROM sessions x
                                   WHERE x.product_id = s.product_id AND x.subtask_id = s.subtask_id)
                       AND NOT EXISTS (SELECT 1 FROM sessions o
                                       WHERE o.product_id = s.product_id AND o.subtask_id = s.subtask_id
                                         AND o.status != 'stopped'))
                GROUP BY s.id
                ORDER BY s.status = 'active' DESC, last_activity DESC, s.id DESC""",
            {"now": to_ts(at)},
        )
        return [dict(row) for row in rows]

    def session_total(self, session_id, at=None):
        row = self.conn.execute(
            f"""SELECT COALESCE(SUM({SECONDS.format(start="start", end="COALESCE(end, :now)")}), 0)
                FROM intervals WHERE session_id = :sid""",
            {"now": to_ts(at or now()), "sid": session_id},
        ).fetchone()
        return row[0]

    def _pause_active(self, at):
        stamp = to_ts(at)
        self.conn.execute(
            """UPDATE intervals SET end = MAX(start, :at), last_seen = :at
               WHERE end IS NULL AND session_id IN (SELECT id FROM sessions WHERE status = 'active')""",
            {"at": stamp},
        )
        self.conn.execute("UPDATE sessions SET status = 'paused' WHERE status = 'active'")

    def _open_interval(self, session_id, at, after_hours):
        stamp = to_ts(at)
        self.conn.execute(
            "INSERT INTO intervals (session_id, start, last_seen, after_hours) VALUES (?, ?, ?, ?)",
            (session_id, stamp, stamp, int(after_hours)),
        )
        self.conn.execute("UPDATE sessions SET status = 'active' WHERE id = ?", (session_id,))

    def start(self, product_id, subtask_id, after_hours=False, at=None):
        """Start work on product + subtask, auto-pausing whatever is running.

        A paused session for the same pair is resumed; otherwise a new session is created.
        """
        at = at or now()
        with self.conn:
            self._pause_active(at)
            self.conn.execute("UPDATE products SET archived = 0 WHERE id = ?", (product_id,))
            row = self.conn.execute(
                """SELECT id FROM sessions
                   WHERE product_id = ? AND subtask_id = ? AND status = 'paused'
                   ORDER BY id DESC LIMIT 1""",
                (product_id, subtask_id),
            ).fetchone()
            if row:
                session_id = row["id"]
            else:
                session_id = self.conn.execute(
                    "INSERT INTO sessions (product_id, subtask_id, status, created_at) VALUES (?, ?, 'paused', ?)",
                    (product_id, subtask_id, to_ts(at)),
                ).lastrowid
            self._open_interval(session_id, at, after_hours)
        return session_id

    def resume(self, session_id, after_hours=False, at=None):
        at = at or now()
        with self.conn:
            row = self.conn.execute("SELECT status FROM sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None or row["status"] != "paused":
                return False
            self._pause_active(at)
            self._open_interval(session_id, at, after_hours)
        return True

    def pause_active(self, at=None):
        with self.conn:
            self._pause_active(at or now())

    def stop(self, session_id, at=None):
        stamp = to_ts(at or now())
        with self.conn:
            self.conn.execute(
                "UPDATE intervals SET end = MAX(start, :at), last_seen = :at WHERE session_id = :sid AND end IS NULL",
                {"at": stamp, "sid": session_id},
            )
            self.conn.execute(
                "UPDATE sessions SET status = 'stopped', stopped_at = ? WHERE id = ?", (stamp, session_id)
            )

    def delete_session(self, session_id):
        with self.conn:
            self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    # ------------------------------------------------------------- manual edits

    def session_info(self, session_id):
        row = self.conn.execute(f"SELECT {SESSION_COLUMNS} {SESSION_JOINS} WHERE s.id = ?", (session_id,)).fetchone()
        return dict(row) if row else None

    def session_days(self, session_id):
        """Number of distinct days the session has intervals on."""
        row = self.conn.execute(
            "SELECT COUNT(DISTINCT substr(start, 1, 10)) FROM intervals WHERE session_id = ?", (session_id,)
        ).fetchone()
        return row[0]

    def day_intervals(self, session_id, day_start, day_end):
        """Intervals of a session overlapping [day_start, day_end), oldest first (end None = running)."""
        rows = self.conn.execute(
            """SELECT id, start, end FROM intervals
               WHERE session_id = ? AND start < ? AND COALESCE(end, ?) > ?
               ORDER BY start""",
            (session_id, to_ts(day_end), to_ts(now()), to_ts(day_start)),
        )
        return [{"id": r["id"], "start": from_ts(r["start"]), "end": from_ts(r["end"])} for r in rows]

    def find_overlap(self, start, end, exclude_ids=()):
        """First interval (any session) overlapping [start, end), ignoring `exclude_ids`; None if free."""
        exclude = list(exclude_ids)
        skip = f"AND i.id NOT IN ({','.join('?' * len(exclude))})" if exclude else ""
        row = self.conn.execute(
            f"""SELECT i.id, i.start, COALESCE(i.end, ?) AS end, p.name AS product, t.name AS subtask
                FROM intervals i
                JOIN sessions s ON s.id = i.session_id
                JOIN products p ON p.id = s.product_id
                JOIN subtasks t ON t.id = s.subtask_id
                WHERE i.start < ? AND COALESCE(i.end, ?) > ? {skip}
                ORDER BY i.start LIMIT 1""",
            [to_ts(now()), to_ts(end), to_ts(now()), to_ts(start), *exclude],
        ).fetchone()
        if row is None:
            return None
        return {"product": row["product"], "subtask": row["subtask"],
                "start": from_ts(row["start"]), "end": from_ts(row["end"])}

    def save_session_edit(self, session_id, product_id, subtask_id, intervals, deleted):
        """Apply a journal edit atomically: move the session to product+subtask, update/insert
        intervals ([(id or None, start, end)]) and delete the ids in `deleted`.
        A session left without intervals is deleted."""
        with self.conn:
            self.conn.execute("UPDATE sessions SET product_id = ?, subtask_id = ? WHERE id = ?",
                              (product_id, subtask_id, session_id))
            for interval_id in deleted:
                self.conn.execute("DELETE FROM intervals WHERE id = ? AND session_id = ?", (interval_id, session_id))
            for interval_id, start, end in intervals:
                if interval_id is None:
                    self.conn.execute(
                        "INSERT INTO intervals (session_id, start, end, last_seen) VALUES (?, ?, ?, ?)",
                        (session_id, to_ts(start), to_ts(end), to_ts(end)),
                    )
                else:
                    self.conn.execute(
                        "UPDATE intervals SET start = ?, end = ?, last_seen = ? WHERE id = ? AND session_id = ?",
                        (to_ts(start), to_ts(end), to_ts(end), interval_id, session_id),
                    )
            left = self.conn.execute("SELECT 1 FROM intervals WHERE session_id = ? LIMIT 1", (session_id,)).fetchone()
            if not left:
                self.conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))

    def add_manual(self, product_id, subtask_id, start, end):
        """Forgotten time: goes into the paused session of that pair if there is one,
        otherwise into a new finished session. Returns the session id."""
        with self.conn:
            row = self.conn.execute(
                """SELECT id FROM sessions WHERE product_id = ? AND subtask_id = ? AND status = 'paused'
                   ORDER BY id DESC LIMIT 1""",
                (product_id, subtask_id),
            ).fetchone()
            if row:
                session_id = row["id"]
            else:
                session_id = self.conn.execute(
                    """INSERT INTO sessions (product_id, subtask_id, status, created_at, stopped_at)
                       VALUES (?, ?, 'stopped', ?, ?)""",
                    (product_id, subtask_id, to_ts(start), to_ts(end)),
                ).lastrowid
            self.conn.execute(
                "INSERT INTO intervals (session_id, start, end, last_seen) VALUES (?, ?, ?, ?)",
                (session_id, to_ts(start), to_ts(end), to_ts(end)),
            )
        return session_id

    def heartbeat(self, at=None):
        """Remember the app was alive, so a crash or power-off loses at most a few seconds."""
        with self.conn:
            self.conn.execute("UPDATE intervals SET last_seen = ? WHERE end IS NULL", (to_ts(at or now()),))

    def recover(self):
        """Close intervals left open by a crash/power-off at their last heartbeat
        (capped by the auto-pause deadline). Returns how many were closed."""
        rows = self.conn.execute("SELECT id, start, last_seen, after_hours FROM intervals WHERE end IS NULL").fetchall()
        with self.conn:
            for row in rows:
                start = from_ts(row["start"])
                end = max(from_ts(row["last_seen"]) or start, start)
                deadline = self.deadline_for(start, row["after_hours"])
                if deadline and end > deadline:
                    end = max(deadline, start)
                self.conn.execute("UPDATE intervals SET end = ? WHERE id = ?", (to_ts(end), row["id"]))
            self.conn.execute("UPDATE sessions SET status = 'paused' WHERE status = 'active'")
        return len(rows)

    # ------------------------------------------------------------------ reports

    def total_between(self, start, end, at=None):
        """Seconds worked (all sessions) within [start, end)."""
        params = {"now": to_ts(at or now()), "pstart": to_ts(start), "pend": to_ts(end)}
        clipped = SECONDS.format(start="MAX(start, :pstart)", end="MIN(COALESCE(end, :now), :pend)")
        row = self.conn.execute(
            f"""SELECT COALESCE(SUM(MAX(0, {clipped})), 0) FROM intervals
                WHERE start < :pend AND COALESCE(end, :now) > :pstart""",
            params,
        ).fetchone()
        return row[0]

    def report_rows(self, start, end, at=None):
        """Every interval overlapping [start, end), clipped to it, with its product/subtask/session."""
        params = {"now": to_ts(at or now()), "pstart": to_ts(start), "pend": to_ts(end)}
        rows = self.conn.execute(
            f"""SELECT {SESSION_COLUMNS}, s.created_at,
                       MAX(i.start, :pstart) AS start,
                       MIN(COALESCE(i.end, :now), :pend) AS end
                FROM intervals i
                JOIN sessions s ON s.id = i.session_id
                JOIN products p ON p.id = s.product_id
                JOIN subtasks t ON t.id = s.subtask_id
                WHERE i.start < :pend AND COALESCE(i.end, :now) > :pstart
                ORDER BY i.start""",
            params,
        )
        return [dict(row) for row in rows]
