"""Layouts: the Panel grid documents the Brain validates, stores and arranges (P02).

A Layout is a set of pages; each page holds one widget list per orientation. Coordinates
are whole cells on the grid of that orientation (landscape 12x6, portrait 6x12).
"""

from __future__ import annotations

import json
import re
import secrets
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BASE_DIR
from app.panels.templates import STARTER_ID, build_from_template

_DEFAULT_DB_PATH = BASE_DIR / "data" / "memory.db"

DEFAULT_ALIAS = "default"
GRID: dict[str, tuple[int, int]] = {"landscape": (12, 6), "portrait": (6, 12)}

_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")
_TYPE_RE = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_LAYOUT_ID_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,79}")
_NAME_MAX = 60
_TITLE_MAX = 40
_MAX_PAGES = 12
_MAX_WIDGETS = 36
_MAX_CONFIG_BYTES = 8192
_SLUG_MAX = 40


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _grid_payload() -> dict[str, dict[str, int]]:
    return {name: {"cols": cols, "rows": rows} for name, (cols, rows) in GRID.items()}


def _clean_name(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("name must be text.")
    clean = value.strip()
    if not 1 <= len(clean) <= _NAME_MAX:
        raise ValueError(f"name must be 1 to {_NAME_MAX} characters.")
    return clean


def _int_value(raw: dict[str, Any], key: str, label: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{label} {key} must be a whole number.")
    return value


def _clean_widget(raw: Any, orientation: str, label: str, seen_ids: set[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object.")
    widget_id = raw.get("id")
    if not isinstance(widget_id, str) or not _ID_RE.fullmatch(widget_id):
        raise ValueError(f"{label} id must be 1 to 32 letters, digits, '_' or '-'.")
    if widget_id in seen_ids:
        raise ValueError(f"Widget id '{widget_id}' is used twice in the {orientation} variant.")
    seen_ids.add(widget_id)

    where = f"Widget '{widget_id}' ({orientation})"
    widget_type = raw.get("type")
    if not isinstance(widget_type, str) or not _TYPE_RE.fullmatch(widget_type):
        raise ValueError(f"{where} type must start with a lowercase letter, up to 64 characters.")

    x = _int_value(raw, "x", where)
    y = _int_value(raw, "y", where)
    w = _int_value(raw, "w", where)
    h = _int_value(raw, "h", where)
    if w < 1 or h < 1:
        raise ValueError(f"{where} must be at least 1 cell wide and 1 cell tall.")
    if x < 0 or y < 0:
        raise ValueError(f"{where} must start at a cell with x and y of 0 or more.")
    cols, rows = GRID[orientation]
    if x + w > cols or y + h > rows:
        raise ValueError(f"{where} does not fit the {cols}x{rows} {orientation} grid.")

    config = raw.get("config")
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise ValueError(f"{where} config must be an object.")
    try:
        encoded = json.dumps(config, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{where} config must be plain JSON data.") from exc
    if len(encoded.encode("utf-8")) > _MAX_CONFIG_BYTES:
        raise ValueError(f"{where} config is larger than {_MAX_CONFIG_BYTES} bytes.")

    return {
        "id": widget_id,
        "type": widget_type,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
        "config": json.loads(encoded),
    }


def _clean_page(raw: Any, index: int, seen_page_ids: set[str]) -> dict[str, Any]:
    label = f"Page {index + 1}"
    if not isinstance(raw, dict):
        raise ValueError(f"{label} must be an object.")
    page_id = raw.get("id")
    if not isinstance(page_id, str) or not _ID_RE.fullmatch(page_id):
        raise ValueError(f"{label} id must be 1 to 32 letters, digits, '_' or '-'.")
    if page_id in seen_page_ids:
        raise ValueError(f"Page id '{page_id}' is used twice.")
    seen_page_ids.add(page_id)

    title = raw.get("title")
    if title is None:
        title = page_id
    if not isinstance(title, str):
        raise ValueError(f"Page '{page_id}' title must be text.")
    title = title.strip() or page_id
    if len(title) > _TITLE_MAX:
        raise ValueError(f"Page '{page_id}' title must be {_TITLE_MAX} characters or fewer.")

    page: dict[str, Any] = {"id": page_id, "title": title}
    for orientation in GRID:
        widgets = raw.get(orientation)
        if widgets is None:
            widgets = []
        if not isinstance(widgets, list):
            raise ValueError(f"Page '{page_id}' {orientation} must be a list.")
        if len(widgets) > _MAX_WIDGETS:
            raise ValueError(
                f"Page '{page_id}' {orientation} has more than {_MAX_WIDGETS} widgets."
            )
        seen_ids: set[str] = set()
        page[orientation] = [
            _clean_widget(widget, orientation, f"Widget {position + 1} on page '{page_id}'", seen_ids)
            for position, widget in enumerate(widgets)
        ]
    return page


def normalize_layout(data: Any, layout_id: str | None = None) -> dict[str, Any]:
    """Validate a Layout document and return a cleaned copy with only the known keys.

    Raises ValueError with a readable message when anything is invalid. ``layout_id``
    overrides the ``id`` inside ``data`` (the routes always pass the URL's id).
    """
    if not isinstance(data, dict):
        raise ValueError("The layout must be an object.")
    resolved_id = layout_id if layout_id is not None else data.get("id")
    if (
        not isinstance(resolved_id, str)
        or not _LAYOUT_ID_RE.fullmatch(resolved_id)
        or resolved_id == DEFAULT_ALIAS
    ):
        raise ValueError(
            "Layout id must be 1 to 80 lowercase letters, digits or '-', and cannot be 'default'."
        )

    name = _clean_name(data.get("name"))

    raw_pages = data.get("pages")
    if not isinstance(raw_pages, list) or not 1 <= len(raw_pages) <= _MAX_PAGES:
        raise ValueError(f"A layout needs 1 to {_MAX_PAGES} pages.")
    seen_page_ids: set[str] = set()
    pages = [_clean_page(raw, index, seen_page_ids) for index, raw in enumerate(raw_pages)]

    return {
        "id": resolved_id,
        "name": name,
        "version": 1,
        "grid": _grid_payload(),
        "pages": pages,
    }


def merge_arrange(
    layout: dict[str, Any],
    page_id: str,
    orientation: str,
    widgets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Return a new Layout with one page variant replaced by a device's arrangement.

    Merge rule: a widget id already on the page keeps its config and type and takes the new
    x, y, w, h; ids missing from ``widgets`` are removed; unknown ids are added with an empty
    config. The other orientation and the other pages are not touched. Raises ValueError for
    bad input and KeyError when the page is unknown.
    """
    if orientation not in GRID:
        raise ValueError("orientation must be 'landscape' or 'portrait'.")
    if not isinstance(widgets, list):
        raise ValueError("widgets must be a list.")

    incoming: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in widgets:
        if not isinstance(raw, dict):
            raise ValueError("Each widget must be an object.")
        widget_id = raw.get("id")
        if not isinstance(widget_id, str) or not _ID_RE.fullmatch(widget_id):
            raise ValueError("Widget id must be 1 to 32 letters, digits, '_' or '-'.")
        if widget_id in seen_ids:
            raise ValueError(f"Widget id '{widget_id}' is sent twice.")
        seen_ids.add(widget_id)
        incoming.append(raw)

    pages = layout.get("pages")
    if not isinstance(pages, list):
        raise KeyError(page_id)
    page = next(
        (item for item in pages if isinstance(item, dict) and item.get("id") == page_id),
        None,
    )
    if page is None:
        raise KeyError(page_id)

    existing = {
        item["id"]: item
        for item in (page.get(orientation) or [])
        if isinstance(item, dict) and "id" in item
    }
    merged: list[dict[str, Any]] = []
    for raw in incoming:
        old = existing.get(raw["id"])
        if old is not None:
            widget_type = old.get("type")
            config = old.get("config", {})
        else:
            widget_type = raw.get("type")
            config = {}
        merged.append(
            {
                "id": raw["id"],
                "type": widget_type,
                "x": raw.get("x"),
                "y": raw.get("y"),
                "w": raw.get("w"),
                "h": raw.get("h"),
                "config": config,
            }
        )

    new_page = dict(page)
    new_page[orientation] = merged
    new_layout = dict(layout)
    new_layout["pages"] = [new_page if item is page else item for item in pages]
    return normalize_layout(new_layout, layout_id=layout.get("id"))


def _resolve(layout_id: str) -> str:
    return STARTER_ID if layout_id == DEFAULT_ALIAS else layout_id


def _encode(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


class LayoutStore:
    """Persistent Layouts in SQLite. The alias 'default' always means the 'starter' Layout."""

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

        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._initialize_db()
        self.ensure_default()

    def _initialize_db(self) -> None:
        """Create the `layouts` table and apply pragmas."""
        with self._lock:
            if not self._is_in_memory:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")
            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS layouts (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        data TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    def close(self) -> None:
        """Close the SQLite connection."""
        with self._lock:
            self._conn.close()

    def _row_to_layout(self, row: sqlite3.Row) -> dict[str, Any]:
        data = json.loads(row["data"])
        data["id"] = row["id"]
        data["name"] = row["name"]
        data["updated_at"] = row["updated_at"]
        return data

    def _select_one(self, layout_id: str) -> dict[str, Any] | None:
        """Fetch one Layout by its resolved id; the caller must hold the lock."""
        row = self._conn.execute("SELECT * FROM layouts WHERE id = ?", (layout_id,)).fetchone()
        return self._row_to_layout(row) if row is not None else None

    def _write(self, layout_id: str, data: dict[str, Any], *, insert: bool) -> None:
        """Store a normalized Layout; the caller must hold the lock."""
        now = _now_iso()
        with self._conn:
            if insert:
                self._conn.execute(
                    "INSERT INTO layouts (id, name, data, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                    (layout_id, data["name"], _encode(data), now, now),
                )
            else:
                self._conn.execute(
                    "UPDATE layouts SET name = ?, data = ?, updated_at = ? WHERE id = ?",
                    (data["name"], _encode(data), now, layout_id),
                )

    def ensure_default(self) -> None:
        """Seed the 'starter' Layout from its template when it is missing."""
        with self._lock:
            exists = self._conn.execute(
                "SELECT 1 FROM layouts WHERE id = ?", (STARTER_ID,)
            ).fetchone()
            if exists is None:
                data = normalize_layout(build_from_template(STARTER_ID), layout_id=STARTER_ID)
                self._write(STARTER_ID, data, insert=True)

    def list(self) -> list[dict[str, str]]:
        """Return the id, name and last update of every Layout, oldest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, name, updated_at FROM layouts ORDER BY created_at, rowid"
            ).fetchall()
            return [
                {"id": row["id"], "name": row["name"], "updated_at": row["updated_at"]}
                for row in rows
            ]

    def get(self, layout_id: str) -> dict[str, Any] | None:
        """Return one Layout (with id, name and updated_at), or None when unknown."""
        with self._lock:
            return self._select_one(_resolve(layout_id))

    def create(self, name: Any, template_id: Any = None) -> dict[str, Any]:
        """Create a Layout from a template (default: starter) with the given name."""
        clean_name = _clean_name(name)
        if template_id is None:
            template_id = STARTER_ID
        if not isinstance(template_id, str):
            raise ValueError("Unknown layout template.")
        try:
            data = build_from_template(template_id)
        except KeyError as exc:
            raise ValueError(f"Unknown layout template '{template_id}'.") from exc

        with self._lock:
            layout_id = self._new_id(clean_name)
            data["name"] = clean_name
            data = normalize_layout(data, layout_id=layout_id)
            self._write(layout_id, data, insert=True)
            created = self._select_one(layout_id)
        assert created is not None
        return created

    def _new_id(self, name: str) -> str:
        """Build '<slug>-<6 hex>' from the name; the caller must hold the lock."""
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:_SLUG_MAX].strip("-")
        if not slug:
            slug = "layout"
        while True:
            candidate = f"{slug}-{secrets.token_hex(3)}"
            taken = self._conn.execute(
                "SELECT 1 FROM layouts WHERE id = ?", (candidate,)
            ).fetchone()
            if taken is None:
                return candidate

    def save(self, layout_id: str, data: Any) -> dict[str, Any] | None:
        """Replace a Layout with a validated document. Returns None when the Layout is unknown."""
        resolved = _resolve(layout_id)
        with self._lock:
            if self._select_one(resolved) is None:
                return None
            clean = normalize_layout(data, layout_id=resolved)
            self._write(resolved, clean, insert=False)
            return self._select_one(resolved)

    def delete(self, layout_id: str) -> bool:
        """Delete a Layout. Returns False when unknown; the starter Layout cannot be deleted."""
        resolved = _resolve(layout_id)
        if resolved == STARTER_ID:
            raise ValueError("The starter layout cannot be deleted.")
        with self._lock:
            with self._conn:
                cursor = self._conn.execute("DELETE FROM layouts WHERE id = ?", (resolved,))
            return cursor.rowcount > 0

    def arrange(
        self,
        layout_id: str,
        page_id: str,
        orientation: str,
        widgets: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        """Apply a device's arrangement to one page variant (see merge_arrange).

        Returns None when the Layout is unknown; raises KeyError or ValueError as merge_arrange does.
        """
        with self._lock:
            current = self._select_one(_resolve(layout_id))
            if current is None:
                return None
            merged = merge_arrange(current, page_id, orientation, widgets)
            self._write(merged["id"], merged, insert=False)
            return self._select_one(merged["id"])
