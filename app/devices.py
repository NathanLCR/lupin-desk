"""Persistent storage of connected devices (Bodies and Panels) in SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BASE_DIR

_DEFAULT_DB_PATH = BASE_DIR / "data" / "memory.db"

ROLES: tuple[str, ...] = ("body", "panel")
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_NAME_MAX = 60
_KIND_MAX = 40
_LAYOUT_ID_MAX = 64
_SCREEN_JSON_MAX = 1000

# Sentinel meaning "argument not provided", so an explicit None can clear a field.
_UNSET: Any = object()


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _encode_screen(screen: Any) -> str:
    """Serialize a screen descriptor; anything not a small dict is stored as an empty object."""
    if not isinstance(screen, dict):
        return "{}"
    try:
        encoded = json.dumps(screen, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return "{}"
    if len(encoded) > _SCREEN_JSON_MAX:
        return "{}"
    return encoded


class DeviceStore:
    """Persistent CRUD of connected devices, their roles and body priority order in SQLite."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._is_in_memory = str(db_path) == ":memory:"
        if db_path is None:
            resolved_path: Path | str = _DEFAULT_DB_PATH
        elif self._is_in_memory:
            resolved_path = ":memory:"
        else:
            resolved_path = Path(db_path)

        self.db_path = resolved_path
        self._lock = threading.Lock()

        if not self._is_in_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Create the `devices` table and apply pragmas."""
        with self._lock:
            if not self._is_in_memory:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")

            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS devices (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL DEFAULT '',
                        kind TEXT NOT NULL DEFAULT '',
                        roles TEXT NOT NULL DEFAULT '["panel"]',
                        layout_id TEXT NULL,
                        body_priority INTEGER NULL,
                        screen TEXT NOT NULL DEFAULT '{}',
                        created_at TEXT NOT NULL,
                        last_seen TEXT NOT NULL
                    )
                    """
                )

    def _row_to_record(self, row: sqlite3.Row) -> dict[str, Any]:
        """Convert a `devices` row into the public record dict."""
        return {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "roles": json.loads(row["roles"]),
            "layout_id": row["layout_id"],
            "body_priority": row["body_priority"],
            "screen": json.loads(row["screen"]),
            "created_at": row["created_at"],
            "last_seen": row["last_seen"],
        }

    def _select_one(self, device_id: str) -> dict[str, Any] | None:
        """Fetch one device record; the caller must hold the lock."""
        row = self._conn.execute(
            "SELECT * FROM devices WHERE id = ?", (device_id,)
        ).fetchone()
        return self._row_to_record(row) if row is not None else None

    def close(self) -> None:
        """Close the SQLite connection safely."""
        with self._lock:
            self._conn.close()

    def upsert_hello(
        self,
        device_id: str,
        *,
        name: str = "",
        kind: str = "",
        screen: dict | None = None,
    ) -> dict:
        """Register a device on hello, or refresh an existing one without touching name or roles."""
        if not isinstance(device_id, str) or not DEVICE_ID_RE.match(device_id):
            raise ValueError("Invalid device id")

        clean_kind = (kind or "").strip()[:_KIND_MAX]
        encoded_screen = _encode_screen(screen)
        now = _now_iso()

        with self._lock:
            existing = self._select_one(device_id)
            with self._conn:
                if existing is None:
                    clean_name = (name or "").strip()[:_NAME_MAX]
                    if not clean_name:
                        clean_name = "Device " + device_id[:4]
                    self._conn.execute(
                        """
                        INSERT INTO devices (
                            id, name, kind, roles, layout_id, body_priority,
                            screen, created_at, last_seen
                        ) VALUES (?, ?, ?, ?, NULL, NULL, ?, ?, ?)
                        """,
                        (
                            device_id,
                            clean_name,
                            clean_kind,
                            json.dumps(["panel"]),
                            encoded_screen,
                            now,
                            now,
                        ),
                    )
                else:
                    self._conn.execute(
                        "UPDATE devices SET kind = ?, screen = ?, last_seen = ? WHERE id = ?",
                        (clean_kind, encoded_screen, now, device_id),
                    )
            record = self._select_one(device_id)
        assert record is not None
        return record

    def get(self, device_id: str) -> dict | None:
        """Return one device record, or None when it is unknown."""
        with self._lock:
            return self._select_one(device_id)

    def list(self) -> list[dict]:
        """Return all devices, most recently seen first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM devices ORDER BY last_seen DESC, rowid DESC"
            ).fetchall()
            return [self._row_to_record(row) for row in rows]

    def touch(self, device_id: str) -> None:
        """Refresh the last_seen timestamp of a device; unknown ids are ignored."""
        with self._lock:
            with self._conn:
                self._conn.execute(
                    "UPDATE devices SET last_seen = ? WHERE id = ?",
                    (_now_iso(), device_id),
                )

    def update(
        self,
        device_id: str,
        *,
        name: Any = _UNSET,
        roles: Any = _UNSET,
        layout_id: Any = _UNSET,
        body_priority: Any = _UNSET,
    ) -> dict | None:
        """Update user-editable fields of a device. Returns None when the device is unknown."""
        assignments: dict[str, Any] = {}

        if name is not _UNSET:
            if not isinstance(name, str) or not name.strip():
                raise ValueError("name must be a non-empty string")
            assignments["name"] = name.strip()[:_NAME_MAX]

        if roles is not _UNSET:
            if not isinstance(roles, (list, tuple)) or not roles:
                raise ValueError("roles must be a non-empty list")
            if not all(isinstance(role, str) and role in ROLES for role in roles):
                raise ValueError(f"roles must be a subset of {list(ROLES)}")
            requested = set(roles)
            ordered = [role for role in ROLES if role in requested]
            assignments["roles"] = json.dumps(ordered)

        if layout_id is not _UNSET:
            if layout_id is not None and (
                not isinstance(layout_id, str) or len(layout_id) > _LAYOUT_ID_MAX
            ):
                raise ValueError("layout_id must be a string of at most 64 characters or None")
            assignments["layout_id"] = layout_id

        if body_priority is not _UNSET:
            if body_priority is not None and (
                isinstance(body_priority, bool)
                or not isinstance(body_priority, int)
                or body_priority < 0
            ):
                raise ValueError("body_priority must be a non-negative integer or None")
            assignments["body_priority"] = body_priority

        with self._lock:
            if self._select_one(device_id) is None:
                return None
            if assignments:
                columns = ", ".join(f"{column} = ?" for column in assignments)
                with self._conn:
                    self._conn.execute(
                        f"UPDATE devices SET {columns} WHERE id = ?",
                        (*assignments.values(), device_id),
                    )
            return self._select_one(device_id)

    def set_body_priority_order(self, order: list[str]) -> None:
        """Give listed devices body_priority 0, 1, 2... in order; every other device gets None."""
        with self._lock:
            known_ids = {
                row["id"] for row in self._conn.execute("SELECT id FROM devices").fetchall()
            }
            ordered: list[str] = []
            for device_id in order:
                if device_id in known_ids and device_id not in ordered:
                    ordered.append(device_id)

            with self._conn:
                self._conn.execute("UPDATE devices SET body_priority = NULL")
                for priority, device_id in enumerate(ordered):
                    self._conn.execute(
                        "UPDATE devices SET body_priority = ? WHERE id = ?",
                        (priority, device_id),
                    )
