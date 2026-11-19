"""Persistent Control Deck data: macros, webhooks and rules (sqlite, same file as the memory).

Macros only chain whitelisted action IDs (MACRO_ACTIONS). Webhook secrets are generated here,
with ``secrets``, and are only ever read back by Mac-only routes. Rules never hold more than
the name of an app or a Signal kind, and the page to switch to.
"""

from __future__ import annotations

import hmac
import json
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

MAX_MACRO_STEPS = 10
MAX_STEP_DELAY_MS = 2000
MAX_TOTAL_DELAY_MS = 10000
MAX_MACROS = 30
MAX_WEBHOOKS = 20
MAX_RULES = 20
NAME_MAX = 40
APP_NAME_MAX = 60
VALUE_MAX_CHARS = 200

# The only actions a macro step may run. Nothing that writes, deletes or runs free text.
MACRO_ACTIONS = frozenset(
    {
        "volume.up",
        "volume.down",
        "volume.mute",
        "mic.toggle",
        "media.play_pause",
        "media.next",
        "media.previous",
        "shortcut.run",
    }
)

RULE_TRIGGERS = frozenset({"app_front", "signal"})

_SLUG_RE = re.compile(r"^[a-z0-9_]{1,64}$")
_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_PAGE_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, label: str, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text.")
    clean = value.strip()
    if not 1 <= len(clean) <= limit or _CONTROL_RE.search(clean):
        raise ValueError(f"{label} must be 1 to {limit} characters.")
    return clean


def validate_steps(steps: Any) -> list[dict[str, Any]]:
    """Return clean macro steps, or raise ValueError. Unknown keys are dropped."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_MACRO_STEPS:
        raise ValueError(f"A macro has 1 to {MAX_MACRO_STEPS} steps.")
    clean: list[dict[str, Any]] = []
    total_delay = 0
    for step in steps:
        if not isinstance(step, dict):
            raise ValueError("Each step must be an object.")
        action = step.get("action")
        if not isinstance(action, str) or action not in MACRO_ACTIONS:
            raise ValueError("Step action is not allowed in a macro.")
        args: dict[str, Any] = {}
        if action == "shortcut.run":
            raw_args = step.get("args")
            slug = raw_args.get("slug") if isinstance(raw_args, dict) else None
            if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
                raise ValueError("shortcut.run needs a valid slug.")
            args = {"slug": slug}
        delay = step.get("delay_ms", 0)
        if isinstance(delay, bool) or not isinstance(delay, int) or not 0 <= delay <= MAX_STEP_DELAY_MS:
            raise ValueError(f"delay_ms must be 0 to {MAX_STEP_DELAY_MS}.")
        total_delay += delay
        clean.append({"action": action, "args": args, "delay_ms": delay})
    if total_delay > MAX_TOTAL_DELAY_MS:
        raise ValueError("The delays of a macro add up to at most 10 seconds.")
    return clean


class ControlStore:
    def __init__(self, db_path: Path | str) -> None:
        if str(db_path) != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS control_macros (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    steps TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control_webhooks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    secret TEXT NOT NULL UNIQUE,
                    emit_signal INTEGER NOT NULL DEFAULT 1,
                    last_value TEXT,
                    last_at TEXT,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS control_rules (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trigger TEXT NOT NULL,
                    match TEXT NOT NULL,
                    page_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------ macros

    @staticmethod
    def _macro(row: sqlite3.Row) -> dict[str, Any]:
        return {"id": row["id"], "name": row["name"], "steps": json.loads(row["steps"])}

    def list_macros(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM control_macros ORDER BY id").fetchall()
        return [self._macro(r) for r in rows]

    def get_macro(self, macro_id: int) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM control_macros WHERE id = ?", (macro_id,)).fetchone()
        return self._macro(row) if row else None

    def add_macro(self, name: Any, steps: Any) -> dict[str, Any]:
        clean_name = _clean_text(name, "name", NAME_MAX)
        clean_steps = validate_steps(steps)
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM control_macros").fetchone()[0]
            if count >= MAX_MACROS:
                raise ValueError("Too many macros.")
            cur = self._conn.execute(
                "INSERT INTO control_macros (name, steps, created_at) VALUES (?, ?, ?)",
                (clean_name, json.dumps(clean_steps), _now_iso()),
            )
            self._conn.commit()
            macro_id = int(cur.lastrowid)
        return {"id": macro_id, "name": clean_name, "steps": clean_steps}

    def update_macro(self, macro_id: int, name: Any = None, steps: Any = None) -> dict[str, Any] | None:
        current = self.get_macro(macro_id)
        if current is None:
            return None
        new_name = _clean_text(name, "name", NAME_MAX) if name is not None else current["name"]
        new_steps = validate_steps(steps) if steps is not None else current["steps"]
        with self._lock:
            self._conn.execute(
                "UPDATE control_macros SET name = ?, steps = ? WHERE id = ?",
                (new_name, json.dumps(new_steps), macro_id),
            )
            self._conn.commit()
        return {"id": macro_id, "name": new_name, "steps": new_steps}

    def remove_macro(self, macro_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM control_macros WHERE id = ?", (macro_id,))
            self._conn.commit()
            return cur.rowcount > 0

    # ---------------------------------------------------------------- webhooks

    @staticmethod
    def _hook(row: sqlite3.Row, *, with_secret: bool) -> dict[str, Any]:
        out: dict[str, Any] = {
            "id": row["id"],
            "name": row["name"],
            "emit_signal": bool(row["emit_signal"]),
            "value": row["last_value"],
            "at": row["last_at"],
        }
        if with_secret:
            out["path"] = f"/hooks/{row['secret']}"
        return out

    def list_webhooks(self, *, with_secret: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM control_webhooks ORDER BY id").fetchall()
        return [self._hook(r, with_secret=with_secret) for r in rows]

    def add_webhook(self, name: Any, emit_signal: bool = True) -> dict[str, Any]:
        clean_name = _clean_text(name, "name", NAME_MAX)
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM control_webhooks").fetchone()[0]
            if count >= MAX_WEBHOOKS:
                raise ValueError("Too many webhooks.")
            cur = self._conn.execute(
                "INSERT INTO control_webhooks (name, secret, emit_signal, created_at) VALUES (?, ?, ?, ?)",
                (clean_name, secrets.token_urlsafe(24), 1 if emit_signal else 0, _now_iso()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM control_webhooks WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._hook(row, with_secret=True)

    def rotate_webhook(self, hook_id: int) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE control_webhooks SET secret = ? WHERE id = ?", (secrets.token_urlsafe(24), hook_id)
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
            row = self._conn.execute("SELECT * FROM control_webhooks WHERE id = ?", (hook_id,)).fetchone()
        return self._hook(row, with_secret=True)

    def remove_webhook(self, hook_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM control_webhooks WHERE id = ?", (hook_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def find_webhook_by_secret(self, secret: str) -> dict[str, Any] | None:
        """Constant-time match of a path secret against every webhook. None when unknown."""
        found: sqlite3.Row | None = None
        with self._lock:
            rows = self._conn.execute("SELECT * FROM control_webhooks").fetchall()
        for row in rows:
            if hmac.compare_digest(row["secret"].encode(), secret.encode()):
                found = row
        return self._hook(found, with_secret=False) if found is not None else None

    def record_webhook_value(self, hook_id: int, value: str | None) -> dict[str, Any] | None:
        at = _now_iso()
        with self._lock:
            self._conn.execute(
                "UPDATE control_webhooks SET last_value = ?, last_at = ? WHERE id = ?", (value, at, hook_id)
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM control_webhooks WHERE id = ?", (hook_id,)).fetchone()
        return self._hook(row, with_secret=False) if row else None

    # ------------------------------------------------------------------- rules

    @staticmethod
    def _rule(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "trigger": row["trigger"],
            "match": row["match"],
            "page_id": row["page_id"],
            "enabled": bool(row["enabled"]),
        }

    def list_rules(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM control_rules ORDER BY id").fetchall()
        return [self._rule(r) for r in rows]

    def add_rule(self, trigger: Any, match: Any, page_id: Any) -> dict[str, Any]:
        if not isinstance(trigger, str) or trigger not in RULE_TRIGGERS:
            raise ValueError("trigger must be app_front or signal.")
        if trigger == "app_front":
            clean_match = _clean_text(match, "app", APP_NAME_MAX)
        else:
            if not isinstance(match, str) or not _KIND_RE.fullmatch(match):
                raise ValueError("signal kind is not valid.")
            clean_match = match
        if not isinstance(page_id, str) or not _PAGE_RE.fullmatch(page_id):
            raise ValueError("page_id is not valid.")
        with self._lock:
            count = self._conn.execute("SELECT COUNT(*) FROM control_rules").fetchone()[0]
            if count >= MAX_RULES:
                raise ValueError("Too many rules.")
            cur = self._conn.execute(
                "INSERT INTO control_rules (trigger, match, page_id, created_at) VALUES (?, ?, ?, ?)",
                (trigger, clean_match, page_id, _now_iso()),
            )
            self._conn.commit()
            row = self._conn.execute("SELECT * FROM control_rules WHERE id = ?", (cur.lastrowid,)).fetchone()
        return self._rule(row)

    def set_rule_enabled(self, rule_id: int, enabled: bool) -> dict[str, Any] | None:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE control_rules SET enabled = ? WHERE id = ?", (1 if enabled else 0, rule_id)
            )
            self._conn.commit()
            if cur.rowcount == 0:
                return None
            row = self._conn.execute("SELECT * FROM control_rules WHERE id = ?", (rule_id,)).fetchone()
        return self._rule(row)

    def remove_rule(self, rule_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM control_rules WHERE id = ?", (rule_id,))
            self._conn.commit()
            return cur.rowcount > 0
