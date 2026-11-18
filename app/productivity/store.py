"""Tasks, notes and habits persisted in SQLite, with an injectable clock for "now" and "today"."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from app.devices import _DEFAULT_DB_PATH

TITLE_MAX = 200
NOTE_MAX = 2000
HABIT_NAME_MAX = 80
STREAK_LOOKBACK_DAYS = 400

_TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _clean_text(value: Any, field: str, max_len: int, *, collapse: bool) -> str:
    """Strip a text field and check its length; collapse inner whitespace when asked."""
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    clean = " ".join(value.split()) if collapse else value.strip()
    if not 1 <= len(clean) <= max_len:
        raise ValueError(f"{field} must be 1 to {max_len} characters")
    return clean


def _fold(text: str) -> str:
    """Normalize text for matching: drop accents and combining marks, then casefold."""
    decomposed = unicodedata.normalize("NFKD", text)
    unaccented = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return unaccented.casefold()


def _match_needle(query: Any) -> str:
    """Return the folded search needle for a query; empty string means "match nothing"."""
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    return _fold(" ".join(query.split()))


def _parse_day(value: Any) -> date:
    """Parse a strict YYYY-MM-DD string into a date."""
    if not isinstance(value, str) or not _DAY_RE.fullmatch(value):
        raise ValueError("day must be a YYYY-MM-DD string")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("day must be a valid YYYY-MM-DD date") from exc


def _clean_days(days: Any) -> list[int]:
    """Validate weekday numbers (0=Monday..6=Sunday); None or empty means every day."""
    if days is None:
        return []
    if not isinstance(days, (list, tuple)):
        raise ValueError("days must be a list of weekday numbers 0 (Monday) to 6 (Sunday)")
    for weekday in days:
        if isinstance(weekday, bool) or not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise ValueError("days must be weekday numbers 0 (Monday) to 6 (Sunday)")
    return sorted(set(days))


def _clean_time(value: Any) -> str | None:
    """Validate an "HH:MM" 24-hour time, or accept None for a habit without a reminder."""
    if value is None:
        return None
    if not isinstance(value, str) or not _TIME_RE.fullmatch(value):
        raise ValueError('time must be "HH:MM" in 24-hour format, or None')
    return value


def _is_scheduled(days: list[int], weekday: int) -> bool:
    """A habit with no weekdays set is scheduled every day."""
    return not days or weekday in days


def _streak(days: list[int], checked_days: set[str], today: date) -> int:
    """Count consecutive scheduled days with a check-in, walking back from today.

    An unchecked scheduled day today does not break the streak; any other
    unchecked scheduled day does. Unscheduled days are skipped.
    """
    streak = 0
    for offset in range(STREAK_LOOKBACK_DAYS):
        day = today - timedelta(days=offset)
        if not _is_scheduled(days, day.weekday()):
            continue
        if day.isoformat() in checked_days:
            streak += 1
        elif day == today:
            continue
        else:
            break
    return streak


class ProductivityStore:
    """Persistent tasks, notes and habits (with check-ins) in SQLite."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        clock: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._is_in_memory = str(db_path) == ":memory:"
        if db_path is None:
            resolved_path: Path | str = _DEFAULT_DB_PATH
        elif self._is_in_memory:
            resolved_path = ":memory:"
        else:
            resolved_path = Path(db_path)

        self.db_path = resolved_path
        self._lock = threading.Lock()
        self._clock = clock

        if not self._is_in_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Create the productivity tables and apply pragmas."""
        with self._lock:
            if not self._is_in_memory:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")

            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        done INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        done_at TEXT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS notes (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        text TEXT NOT NULL,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS habits (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        days TEXT NOT NULL DEFAULT '[]',
                        time TEXT NULL,
                        created_at TEXT NOT NULL,
                        last_notified_day TEXT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS habit_checkins (
                        habit_id INTEGER NOT NULL,
                        day TEXT NOT NULL,
                        PRIMARY KEY (habit_id, day)
                    )
                    """
                )

    def close(self) -> None:
        """Close the SQLite connection safely."""
        with self._lock:
            self._conn.close()

    def _now_iso(self) -> str:
        """Return the clock's local time as an ISO-8601 string (seconds precision)."""
        return self._clock().isoformat(timespec="seconds")

    def _today(self) -> date:
        """Return the clock's local date."""
        return self._clock().date()

    # ------------------------------------------------------------------ tasks

    @staticmethod
    def _task_record(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "done": bool(row["done"]),
            "created_at": row["created_at"],
            "done_at": row["done_at"],
        }

    def _fetch_task(self, task_id: int) -> sqlite3.Row | None:
        """Fetch one task row; the caller must hold the lock."""
        return self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    def add_task(self, title: str) -> dict[str, Any]:
        """Add an open task. Title is stripped and inner whitespace collapsed (1 to 200 chars)."""
        clean_title = _clean_text(title, "title", TITLE_MAX, collapse=True)
        now = self._now_iso()
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO tasks (title, done, created_at, done_at) VALUES (?, 0, ?, NULL)",
                    (clean_title, now),
                )
                task_id = cursor.lastrowid
            row = self._fetch_task(task_id)  # type: ignore[arg-type]
        assert row is not None
        return self._task_record(row)

    def list_tasks(self, include_done: bool = False) -> list[dict[str, Any]]:
        """Return tasks ordered by id; open tasks only unless include_done is True."""
        sql = "SELECT * FROM tasks"
        if not include_done:
            sql += " WHERE done = 0"
        sql += " ORDER BY id"
        with self._lock:
            rows = self._conn.execute(sql).fetchall()
        return [self._task_record(row) for row in rows]

    def set_task_done(self, task_id: int, done: bool = True) -> dict[str, Any] | None:
        """Mark a task done or open again. Returns None for an unknown id."""
        with self._lock:
            row = self._fetch_task(task_id)
            if row is None:
                return None
            if done:
                already_done = bool(row["done"]) and row["done_at"] is not None
                done_at = row["done_at"] if already_done else self._now_iso()
            else:
                done_at = None
            with self._conn:
                self._conn.execute(
                    "UPDATE tasks SET done = ?, done_at = ? WHERE id = ?",
                    (1 if done else 0, done_at, task_id),
                )
            updated = self._fetch_task(task_id)
        assert updated is not None
        return self._task_record(updated)

    def find_tasks(self, query: str, include_done: bool = False) -> list[dict[str, Any]]:
        """Return tasks whose title contains the query (case and accent insensitive)."""
        needle = _match_needle(query)
        if not needle:
            return []
        return [
            task
            for task in self.list_tasks(include_done=include_done)
            if needle in _fold(task["title"])
        ]

    def remove_task(self, task_id: int) -> bool:
        """Delete a task. Returns False when the id is unknown."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            return cursor.rowcount > 0

    # ------------------------------------------------------------------ notes

    @staticmethod
    def _note_record(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "text": row["text"], "created_at": row["created_at"]}

    def add_note(self, text: str) -> dict[str, Any]:
        """Add a note (1 to 2000 chars after stripping)."""
        clean_text = _clean_text(text, "text", NOTE_MAX, collapse=False)
        now = self._now_iso()
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "INSERT INTO notes (text, created_at) VALUES (?, ?)",
                    (clean_text, now),
                )
                note_id = cursor.lastrowid
            row = self._conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
        assert row is not None
        return self._note_record(row)

    def list_notes(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return the newest notes first, up to limit."""
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValueError("limit must be a positive integer")
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM notes ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._note_record(row) for row in rows]

    def find_notes(self, query: str) -> list[dict[str, Any]]:
        """Return notes containing the query (case and accent insensitive), newest first."""
        needle = _match_needle(query)
        if not needle:
            return []
        with self._lock:
            rows = self._conn.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
        return [
            self._note_record(row) for row in rows if needle in _fold(row["text"])
        ]

    def remove_note(self, note_id: int) -> bool:
        """Delete a note. Returns False when the id is unknown."""
        with self._lock:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            return cursor.rowcount > 0

    # ----------------------------------------------------------------- habits

    def _checkins_by_habit(self, today: date) -> dict[int, set[str]]:
        """Load check-in days inside the streak lookback window; the caller must hold the lock."""
        floor = (today - timedelta(days=STREAK_LOOKBACK_DAYS)).isoformat()
        rows = self._conn.execute(
            "SELECT habit_id, day FROM habit_checkins WHERE day >= ?", (floor,)
        ).fetchall()
        checked: dict[int, set[str]] = {}
        for row in rows:
            checked.setdefault(row["habit_id"], set()).add(row["day"])
        return checked

    def _habit_records(self, rows: list[sqlite3.Row], today: date) -> list[dict[str, Any]]:
        """Build public habit dicts with streak and done_today; the caller must hold the lock."""
        checked = self._checkins_by_habit(today)
        records: list[dict[str, Any]] = []
        for row in rows:
            days = json.loads(row["days"])
            checked_days = checked.get(row["id"], set())
            records.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "days": days,
                    "time": row["time"],
                    "created_at": row["created_at"],
                    "streak": _streak(days, checked_days, today),
                    "done_today": today.isoformat() in checked_days,
                }
            )
        return records

    def _habit_rows(self, sql: str = "SELECT * FROM habits ORDER BY id", params: tuple = ()) -> list[sqlite3.Row]:
        """Fetch habit rows; the caller must hold the lock."""
        return self._conn.execute(sql, params).fetchall()

    def add_habit(
        self,
        name: str,
        days: list[int] | None = None,
        time: str | None = None,
    ) -> dict[str, Any]:
        """Add a habit. days=None or [] means every day; time is "HH:MM" or None."""
        clean_name = _clean_text(name, "name", HABIT_NAME_MAX, collapse=True)
        clean_days = _clean_days(days)
        clean_time = _clean_time(time)
        now = self._now_iso()
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    """
                    INSERT INTO habits (name, days, time, created_at, last_notified_day)
                    VALUES (?, ?, ?, ?, NULL)
                    """,
                    (clean_name, json.dumps(clean_days), clean_time, now),
                )
                habit_id = cursor.lastrowid
            rows = self._habit_rows("SELECT * FROM habits WHERE id = ?", (habit_id,))
            return self._habit_records(rows, self._today())[0]

    def list_habits(self) -> list[dict[str, Any]]:
        """Return all habits ordered by id."""
        with self._lock:
            rows = self._habit_rows()
            return self._habit_records(rows, self._today())

    def get_habit(self, habit_id: int) -> dict[str, Any] | None:
        """Return one habit, or None when the id is unknown."""
        with self._lock:
            rows = self._habit_rows("SELECT * FROM habits WHERE id = ?", (habit_id,))
            if not rows:
                return None
            return self._habit_records(rows, self._today())[0]

    def find_habits(self, query: str) -> list[dict[str, Any]]:
        """Return habits whose name contains the query (case and accent insensitive)."""
        needle = _match_needle(query)
        if not needle:
            return []
        return [habit for habit in self.list_habits() if needle in _fold(habit["name"])]

    def check_in(
        self,
        habit_id: int,
        day: str | None = None,
        done: bool = True,
    ) -> dict[str, Any] | None:
        """Record (done=True) or undo (done=False) a check-in. day defaults to today.

        Returns the updated habit, or None when the habit id is unknown.
        """
        today = self._today()
        target = today if day is None else _parse_day(day)
        with self._lock:
            rows = self._habit_rows("SELECT * FROM habits WHERE id = ?", (habit_id,))
            if not rows:
                return None
            with self._conn:
                if done:
                    self._conn.execute(
                        "INSERT OR IGNORE INTO habit_checkins (habit_id, day) VALUES (?, ?)",
                        (habit_id, target.isoformat()),
                    )
                else:
                    self._conn.execute(
                        "DELETE FROM habit_checkins WHERE habit_id = ? AND day = ?",
                        (habit_id, target.isoformat()),
                    )
            rows = self._habit_rows("SELECT * FROM habits WHERE id = ?", (habit_id,))
            return self._habit_records(rows, today)[0]

    def remove_habit(self, habit_id: int) -> bool:
        """Delete a habit and its check-ins. Returns False when the id is unknown."""
        with self._lock:
            with self._conn:
                self._conn.execute("DELETE FROM habit_checkins WHERE habit_id = ?", (habit_id,))
                cursor = self._conn.execute("DELETE FROM habits WHERE id = ?", (habit_id,))
            return cursor.rowcount > 0

    def due_habits(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Return habits due at `now` (default: the clock).

        Due means: scheduled for that weekday, has a time at or before now's HH:MM,
        not checked in that day, and not already notified that day.
        """
        moment = now if now is not None else self._clock()
        today = moment.date()
        today_iso = today.isoformat()
        current_hhmm = moment.strftime("%H:%M")
        with self._lock:
            rows = self._habit_rows()
            records = self._habit_records(rows, today)
        due: list[dict[str, Any]] = []
        for row, record in zip(rows, records):
            if record["time"] is None:
                continue
            if not _is_scheduled(record["days"], today.weekday()):
                continue
            if record["time"] > current_hhmm:
                continue
            if record["done_today"]:
                continue
            if row["last_notified_day"] == today_iso:
                continue
            due.append(record)
        return due

    def mark_habit_notified(self, habit_id: int, day: str) -> bool:
        """Remember that a habit was notified on `day`. Returns False for an unknown id."""
        day_iso = _parse_day(day).isoformat()
        with self._lock:
            with self._conn:
                cursor = self._conn.execute(
                    "UPDATE habits SET last_notified_day = ? WHERE id = ?",
                    (day_iso, habit_id),
                )
            return cursor.rowcount > 0
