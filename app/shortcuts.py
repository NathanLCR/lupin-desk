"""Persistent storage and default catalog of configurable shortcuts in SQLite."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BASE_DIR

_DEFAULT_DB_PATH = BASE_DIR / "data" / "memory.db"

VALID_ACTION_TYPES: frozenset[str] = frozenset(
    {"keystroke", "app_activate", "mac_command", "agent_prompt"}
)
VALID_CATEGORIES: frozenset[str] = frozenset(
    {"spaces", "capture", "editing", "apps", "media", "custom"}
)
VALID_COLORS: frozenset[str] = frozenset(
    {"cyan", "amber", "violet", "emerald", "rose", "slate"}
)

_SLUG_CLEAN_RE = re.compile(r"[^a-z0-9_]+")


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return datetime.now(timezone.utc).isoformat()


def _strip_accents(text: str) -> str:
    """Strip accents, keeping only base ASCII characters for comparison."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _slugify(text: str) -> str:
    """Convert free text into a safe slug with lowercase letters and underscores."""
    ascii_text = _strip_accents(text).lower().strip()
    replaced = re.sub(r"[\s\-/]+", "_", ascii_text)
    cleaned = _SLUG_CLEAN_RE.sub("", replaced).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned or "shortcut"


def _normalize_trigger(text: str) -> str:
    """Normalize a phrase or voice trigger for accent- and punctuation-tolerant matching."""
    plain = _strip_accents(text).lower().strip()
    plain = re.sub(r"[^\w\s]", " ", plain)
    return re.sub(r"\s+", " ", plain).strip()


# Default catalog pre-mapped to cope with an external display and a hidden Dock on macOS
DEFAULT_SHORTCUTS: tuple[dict[str, Any], ...] = (
    # Spaces & Windows
    {
        "slug": "mission_control",
        "title": "Mission Control",
        "icon": "🪟",
        "category": "spaces",
        "action_type": "mac_command",
        "payload": {"command": "mission_control"},
        "voice_triggers": "mission control, ver todas as janelas, visao geral, workspaces, see all windows, show all windows, overview",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "app_expose",
        "title": "App Exposé",
        "icon": "🗂️",
        "category": "spaces",
        "action_type": "mac_command",
        "payload": {"command": "app_expose"},
        "voice_triggers": "expose, expose do app, janelas do app, app expose, show app windows, app windows",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "space_left",
        "title": "Space Left ⬅️",
        "icon": "⬅️",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "ctrl+left"},
        "voice_triggers": "espaco esquerda, espaco anterior, space left, desktop esquerda, previous space, desktop left, move left a desktop",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "space_right",
        "title": "Space Right ➡️",
        "icon": "➡️",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "ctrl+right"},
        "voice_triggers": "espaco direita, proximo espaco, space right, desktop direita, next space, desktop right, move right a desktop",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "switch_window",
        "title": "Switch Window",
        "icon": "🔁",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+grave"},
        "voice_triggers": "trocar janela, proxima janela do app, switch window, next window, next app window",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "switch_app",
        "title": "Switch App",
        "icon": "🔀",
        "category": "apps",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+tab"},
        "voice_triggers": "alternar app, trocar app, app anterior, switch app, change app, previous app, switch application",
        "color": "violet",
        "pinned_on_deck": True,
    },
    {
        "slug": "fullscreen_window",
        "title": "Full Screen",
        "icon": "⛶",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "ctrl+cmd+f"},
        "voice_triggers": "tela cheia, fullscreen, maximizar janela, full screen, make it full screen, maximize window",
        "color": "cyan",
        "pinned_on_deck": False,
    },
    {
        "slug": "toggle_dock",
        "title": "Show/Hide Dock",
        "icon": "🧭",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "opt+cmd+d"},
        "voice_triggers": "mostrar dock, ocultar dock, alternar dock, toggle dock, show dock, hide dock, toggle the dock",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    # Capture / Screenshots
    {
        "slug": "screenshot_clipboard",
        "title": "Screenshot Selection → Clipboard",
        "icon": "📋",
        "category": "capture",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+ctrl+shift+4"},
        "voice_triggers": "print clipboard, print selecao clipboard, captura para clipboard, screenshot clipboard, screenshot to clipboard, capture to clipboard",
        "color": "amber",
        "pinned_on_deck": True,
    },
    {
        "slug": "screenshot_file",
        "title": "Screenshot Selection → File",
        "icon": "📸",
        "category": "capture",
        "action_type": "mac_command",
        "payload": {"command": "screenshot_area_file"},
        "voice_triggers": "print arquivo, print selecao arquivo, tirar print, screenshot file, take a screenshot, screenshot to file, capture to file",
        "color": "amber",
        "pinned_on_deck": True,
    },
    {
        "slug": "screenshot_full",
        "title": "Screenshot Full Screen",
        "icon": "🖼️",
        "category": "capture",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+shift+3"},
        "voice_triggers": "print tela inteira, captura tela inteira, screenshot full, full screenshot, capture whole screen, screenshot whole screen",
        "color": "amber",
        "pinned_on_deck": False,
    },
    # Editing & Search ("No Memorizing")
    {
        "slug": "find",
        "title": "Find",
        "icon": "🔍",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+f"},
        "voice_triggers": "pesquisar, buscar na pagina, procurar, find, search, search the page, find on page",
        "color": "emerald",
        "pinned_on_deck": True,
    },
    {
        "slug": "find_replace",
        "title": "Find and Replace",
        "icon": "🔄",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+opt+f"},
        "voice_triggers": "pesquisar e substituir, substituir, find and replace, replace, search and replace",
        "color": "emerald",
        "pinned_on_deck": True,
    },
    {
        "slug": "paste_plain",
        "title": "Paste Without Formatting",
        "icon": "📄",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "opt+cmd+shift+v"},
        "voice_triggers": "colar sem formatacao, colar limpo, paste plain, paste without formatting, paste as plain text, plain paste",
        "color": "emerald",
        "pinned_on_deck": True,
    },
    {
        "slug": "undo",
        "title": "Undo",
        "icon": "↩️",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+z"},
        "voice_triggers": "desfazer, voltar acao, undo, undo that, go back one step",
        "color": "emerald",
        "pinned_on_deck": True,
    },
    {
        "slug": "redo",
        "title": "Redo",
        "icon": "↪️",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+shift+z"},
        "voice_triggers": "refazer, avancar acao, redo, redo that, go forward one step",
        "color": "emerald",
        "pinned_on_deck": False,
    },
    # Media & System & Focus
    {
        "slug": "play_pause",
        "title": "Play / Pause",
        "icon": "⏯️",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "play_pause"},
        "voice_triggers": "play pause, pausar musica, tocar musica, retomar musica, pause music, play music, resume music",
        "color": "rose",
        "pinned_on_deck": True,
    },
    {
        "slug": "next_track",
        "title": "Next Track",
        "icon": "⏭️",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "next_track"},
        "voice_triggers": "proxima faixa, proxima musica, pular musica, next track, next song, skip song, skip track",
        "color": "rose",
        "pinned_on_deck": True,
    },
    {
        "slug": "prev_track",
        "title": "Previous Track",
        "icon": "⏮️",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "prev_track"},
        "voice_triggers": "faixa anterior, musica anterior, voltar musica, prev track, previous track, previous song, last song",
        "color": "rose",
        "pinned_on_deck": False,
    },
    {
        "slug": "volume_up",
        "title": "Volume Up",
        "icon": "🔊",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "volume_up"},
        "voice_triggers": "aumentar volume, subir volume, volume mais, volume up, louder, turn it up, increase volume",
        "color": "rose",
        "pinned_on_deck": True,
    },
    {
        "slug": "volume_down",
        "title": "Volume Down",
        "icon": "🔉",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "volume_down"},
        "voice_triggers": "diminuir volume, abaixar volume, volume menos, volume down, quieter, turn it down, decrease volume",
        "color": "rose",
        "pinned_on_deck": True,
    },
    {
        "slug": "volume_mute",
        "title": "Mute",
        "icon": "🔇",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "volume_mute"},
        "voice_triggers": "mudo, mutar, silenciar som, mute, mute the sound, mute volume, silence",
        "color": "rose",
        "pinned_on_deck": False,
    },
    {
        "slug": "lock_screen",
        "title": "Lock Screen",
        "icon": "🔒",
        "category": "apps",
        "action_type": "mac_command",
        "payload": {"command": "lock_screen"},
        "voice_triggers": "bloquear tela, travar mac, lock screen, lock my mac, lock the screen, lock mac",
        "color": "violet",
        "pinned_on_deck": True,
    },
    {
        "slug": "pomodoro_25",
        "title": "Pomodoro 25m",
        "icon": "🍅",
        "category": "custom",
        "action_type": "mac_command",
        "payload": {"command": "pomodoro_start"},
        "voice_triggers": "pomodoro, iniciar pomodoro, foco 25 minutos, start pomodoro, focus 25 minutes, pomodoro timer",
        "color": "amber",
        "pinned_on_deck": True,
    },
)


# Portuguese-only values the catalog shipped with. Kept only to tell untouched legacy rows
# (safe to upgrade to the bilingual defaults) from rows the user edited.
_LEGACY_PT_DEFAULTS: dict[str, tuple[str, str]] = {
    'mission_control': ('Mission Control', 'mission control, ver todas as janelas, visao geral, workspaces'),
    'app_expose': ('Exposé do App', 'expose, expose do app, janelas do app, app expose'),
    'space_left': ('Espaço ⬅️', 'espaco esquerda, espaco anterior, space left, desktop esquerda'),
    'space_right': ('Espaço ➡️', 'espaco direita, proximo espaco, space right, desktop direita'),
    'switch_window': ('Trocar Janela', 'trocar janela, proxima janela do app, switch window'),
    'switch_app': ('Alternar App', 'alternar app, trocar app, app anterior, switch app'),
    'fullscreen_window': ('Tela Cheia', 'tela cheia, fullscreen, maximizar janela'),
    'toggle_dock': ('Mostrar/Ocultar Dock', 'mostrar dock, ocultar dock, alternar dock, toggle dock'),
    'screenshot_clipboard': ('Print Seleção → Clipboard', 'print clipboard, print selecao clipboard, captura para clipboard, screenshot clipboard'),
    'screenshot_file': ('Print Seleção → Arquivo', 'print arquivo, print selecao arquivo, tirar print, screenshot file'),
    'screenshot_full': ('Print Tela Inteira', 'print tela inteira, captura tela inteira, screenshot full'),
    'find': ('Pesquisar', 'pesquisar, buscar na pagina, procurar, find'),
    'find_replace': ('Pesquisar e Substituir', 'pesquisar e substituir, substituir, find and replace'),
    'paste_plain': ('Colar Sem Formatação', 'colar sem formatacao, colar limpo, paste plain'),
    'undo': ('Desfazer', 'desfazer, voltar acao, undo'),
    'redo': ('Refazer', 'refazer, avancar acao, redo'),
    'play_pause': ('Play / Pause', 'play pause, pausar musica, tocar musica, retomar musica'),
    'next_track': ('Próxima Faixa', 'proxima faixa, proxima musica, pular musica, next track'),
    'prev_track': ('Faixa Anterior', 'faixa anterior, musica anterior, voltar musica, prev track'),
    'volume_up': ('Volume +', 'aumentar volume, subir volume, volume mais, volume up'),
    'volume_down': ('Volume -', 'diminuir volume, abaixar volume, volume menos, volume down'),
    'volume_mute': ('Mudo', 'mudo, mutar, silenciar som, mute'),
    'lock_screen': ('Bloquear Tela', 'bloquear tela, travar mac, lock screen'),
    'pomodoro_25': ('Pomodoro 25m', 'pomodoro, iniciar pomodoro, foco 25 minutos'),
}


class ShortcutStore:
    """Persistent CRUD of configurable shortcuts and the default catalog in SQLite."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._is_in_memory = str(db_path) == ":memory:"
        if db_path is None:
            resolved_path: Path | str = _DEFAULT_DB_PATH
        elif self._is_in_memory:
            resolved_path = ":memory:"
        else:
            resolved_path = Path(db_path)

        self.db_path = resolved_path
        self._lock = threading.RLock()

        if not self._is_in_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Create the `shortcuts` table, apply pragmas and seed the defaults if empty."""
        with self._lock:
            if not self._is_in_memory:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")

            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS shortcuts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        slug TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        icon TEXT NOT NULL DEFAULT '⚡',
                        category TEXT NOT NULL DEFAULT 'custom',
                        action_type TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        voice_triggers TEXT NOT NULL DEFAULT '',
                        color TEXT NOT NULL DEFAULT 'cyan',
                        pinned_on_deck INTEGER NOT NULL DEFAULT 0,
                        sort_order INTEGER NOT NULL DEFAULT 0,
                        is_default INTEGER NOT NULL DEFAULT 0,
                        requires_confirmation INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

                # Defensive migration in case another instance created a partial table
                existing_cols = {
                    row["name"]
                    for row in self._conn.execute("PRAGMA table_info(shortcuts)").fetchall()
                }
                migrations = (
                    ("voice_triggers", "TEXT NOT NULL DEFAULT ''"),
                    ("color", "TEXT NOT NULL DEFAULT 'cyan'"),
                    ("pinned_on_deck", "INTEGER NOT NULL DEFAULT 1"),
                    ("sort_order", "INTEGER NOT NULL DEFAULT 0"),
                    ("is_default", "INTEGER NOT NULL DEFAULT 0"),
                    ("requires_confirmation", "INTEGER NOT NULL DEFAULT 0"),
                    ("created_at", "TEXT NOT NULL DEFAULT ''"),
                    ("updated_at", "TEXT NOT NULL DEFAULT ''"),
                )
                for col_name, col_def in migrations:
                    if col_name not in existing_cols:
                        self._conn.execute(
                            f"ALTER TABLE shortcuts ADD COLUMN {col_name} {col_def}"
                        )

                count_row = self._conn.execute(
                    "SELECT COUNT(*) AS total FROM shortcuts"
                ).fetchone()
                if count_row is not None and int(count_row["total"]) == 0:
                    self._seed_defaults_locked()
                else:
                    self._upgrade_legacy_defaults_locked()

    def _upgrade_legacy_defaults_locked(self) -> None:
        """Upgrade default rows still holding the old Portuguese title and triggers (idempotent)."""
        current = {item["slug"]: item for item in DEFAULT_SHORTCUTS}
        for slug, (old_title, old_triggers) in _LEGACY_PT_DEFAULTS.items():
            item = current.get(slug)
            if item is None:
                continue
            self._conn.execute(
                """
                UPDATE shortcuts SET title = ?, voice_triggers = ?, updated_at = ?
                WHERE slug = ? AND title = ? AND voice_triggers = ?
                """,
                (item["title"], item["voice_triggers"], _now_iso(), slug, old_title, old_triggers),
            )

    def _seed_defaults_locked(self) -> None:
        """Populate the default shortcuts in the table (requires the lock and an active transaction)."""
        now = _now_iso()
        for idx, item in enumerate(DEFAULT_SHORTCUTS):
            self._conn.execute(
                """
                INSERT INTO shortcuts (
                    slug, title, icon, category, action_type, payload,
                    voice_triggers, color, pinned_on_deck, sort_order,
                    is_default, requires_confirmation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["slug"],
                    item["title"],
                    item["icon"],
                    item["category"],
                    item["action_type"],
                    json.dumps(item["payload"], ensure_ascii=False),
                    item["voice_triggers"],
                    item["color"],
                    1 if item.get("pinned_on_deck", True) else 0,
                    idx,
                    1,
                    1 if item.get("requires_confirmation", False) else 0,
                    now,
                    now,
                ),
            )

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a SQLite row into a typed dict with the `payload` deserialized."""
        raw_payload = row["payload"]
        try:
            payload = json.loads(raw_payload) if isinstance(raw_payload, str) else {}
        except json.JSONDecodeError:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}

        return {
            "id": int(row["id"]),
            "slug": str(row["slug"]),
            "title": str(row["title"]),
            "icon": str(row["icon"]),
            "category": str(row["category"]),
            "action_type": str(row["action_type"]),
            "payload": payload,
            "voice_triggers": str(row["voice_triggers"] or ""),
            "color": str(row["color"] or "cyan"),
            "pinned_on_deck": bool(row["pinned_on_deck"]),
            "sort_order": int(row["sort_order"]),
            "is_default": bool(row["is_default"]),
            "requires_confirmation": bool(row["requires_confirmation"]),
            "created_at": str(row["created_at"] or ""),
            "updated_at": str(row["updated_at"] or ""),
        }

    @staticmethod
    def _validate_payload(payload: Any) -> dict[str, Any]:
        """Validate and normalize `payload` as a JSON dict."""
        if payload is None:
            return {}
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON payload.") from exc
            payload = parsed
        if not isinstance(payload, dict):
            raise ValueError("The shortcut payload must be a JSON object.")
        return dict(payload)

    @staticmethod
    def _validate_action_type(action_type: Any) -> str:
        """Validate that `action_type` belongs to the supported set."""
        cleaned = str(action_type or "").strip()
        if cleaned not in VALID_ACTION_TYPES:
            raise ValueError(
                f"Invalid action_type: '{cleaned}'. Allowed: {sorted(VALID_ACTION_TYPES)}"
            )
        return cleaned

    @staticmethod
    def _normalize_category(category: Any) -> str:
        """Normalize the category with a safe fallback to `custom`."""
        cleaned = str(category or "").strip().lower()
        if not cleaned:
            return "custom"
        if cleaned == "focus":
            return "custom"
        if cleaned not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category: '{cleaned}'. Allowed: {sorted(VALID_CATEGORIES)}"
            )
        return cleaned

    @staticmethod
    def _normalize_color(color: Any) -> str:
        """Normalize the tile color with a fallback to `cyan`."""
        cleaned = str(color or "cyan").strip().lower()
        return cleaned if cleaned in VALID_COLORS else "cyan"

    def _generate_unique_slug_locked(self, base_text: str) -> str:
        """Generate a unique slug avoiding collisions in the `shortcuts` table."""
        base_slug = _slugify(base_text)
        candidate = base_slug
        suffix = 2
        while True:
            row = self._conn.execute(
                "SELECT 1 FROM shortcuts WHERE slug = ? LIMIT 1",
                (candidate,),
            ).fetchone()
            if row is None:
                return candidate
            candidate = f"{base_slug}_{suffix}"
            suffix += 1

    def _get_row_locked(self, identifier: int | str) -> sqlite3.Row | None:
        """Look up a row by integer `id` or text `slug`."""
        if isinstance(identifier, int) and not isinstance(identifier, bool):
            return self._conn.execute(
                "SELECT * FROM shortcuts WHERE id = ? LIMIT 1",
                (identifier,),
            ).fetchone()

        ident_str = str(identifier).strip()
        if not ident_str:
            return None

        row = self._conn.execute(
            "SELECT * FROM shortcuts WHERE slug = ? LIMIT 1",
            (ident_str,),
        ).fetchone()
        if row is not None:
            return row

        if ident_str.isdigit():
            return self._conn.execute(
                "SELECT * FROM shortcuts WHERE id = ? LIMIT 1",
                (int(ident_str),),
            ).fetchone()
        return None

    def list_shortcuts(self, category: str | None = None) -> list[dict[str, Any]]:
        """List all shortcuts ordered by `sort_order` and `id`, optionally filtered."""
        with self._lock:
            cleaned_cat = (category or "").strip().lower()
            if cleaned_cat and cleaned_cat not in {"all", "todos"}:
                rows = self._conn.execute(
                    """
                    SELECT * FROM shortcuts
                    WHERE category = ?
                    ORDER BY sort_order ASC, id ASC
                    """,
                    (cleaned_cat,),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """
                    SELECT * FROM shortcuts
                    ORDER BY sort_order ASC, id ASC
                    """
                ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_shortcut(self, identifier: int | str) -> dict[str, Any] | None:
        """Get a shortcut by numeric `id` or `slug`."""
        with self._lock:
            row = self._get_row_locked(identifier)
            return self._row_to_dict(row) if row is not None else None

    def create_shortcut(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new shortcut, validating `action_type` and generating a unique `slug` if omitted."""
        if not isinstance(data, dict):
            raise ValueError("Shortcut data must be a dict.")

        title = str(data.get("title") or "").strip()
        if not title:
            raise ValueError("The shortcut title is required.")

        action_type = self._validate_action_type(data.get("action_type"))
        payload = self._validate_payload(data.get("payload"))
        category = self._normalize_category(data.get("category"))
        color = self._normalize_color(data.get("color"))
        icon = str(data.get("icon") or "⚡").strip() or "⚡"
        voice_triggers = str(data.get("voice_triggers") or "").strip()
        pinned_on_deck = bool(data.get("pinned_on_deck", False))
        is_default = bool(data.get("is_default", False))
        requires_confirmation = bool(data.get("requires_confirmation", False))
        now = _now_iso()

        raw_slug = data.get("slug")
        explicit_slug = str(raw_slug).strip() if raw_slug is not None else ""

        with self._lock, self._conn:
            if explicit_slug:
                slug = _slugify(explicit_slug)
                exists = self._conn.execute(
                    "SELECT 1 FROM shortcuts WHERE slug = ? LIMIT 1",
                    (slug,),
                ).fetchone()
                if exists is not None:
                    raise ValueError(f"A shortcut with slug '{slug}' already exists.")
            else:
                slug = self._generate_unique_slug_locked(title)

            if "sort_order" in data and data["sort_order"] is not None:
                sort_order = int(data["sort_order"])
            else:
                max_row = self._conn.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) AS max_order FROM shortcuts"
                ).fetchone()
                sort_order = int(max_row["max_order"]) + 1 if max_row else 0

            cursor = self._conn.execute(
                """
                INSERT INTO shortcuts (
                    slug, title, icon, category, action_type, payload,
                    voice_triggers, color, pinned_on_deck, sort_order,
                    is_default, requires_confirmation, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    slug,
                    title,
                    icon,
                    category,
                    action_type,
                    json.dumps(payload, ensure_ascii=False),
                    voice_triggers,
                    color,
                    1 if pinned_on_deck else 0,
                    sort_order,
                    1 if is_default else 0,
                    1 if requires_confirmation else 0,
                    now,
                    now,
                ),
            )
            created_id = int(cursor.lastrowid)
            row = self._conn.execute(
                "SELECT * FROM shortcuts WHERE id = ?",
                (created_id,),
            ).fetchone()
            assert row is not None
            return self._row_to_dict(row)

    def update_shortcut(
        self, identifier: int | str, data: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Update fields of an existing shortcut identified by `id` or `slug`."""
        if not isinstance(data, dict):
            raise ValueError("Update data must be a dict.")

        with self._lock, self._conn:
            existing_row = self._get_row_locked(identifier)
            if existing_row is None:
                return None

            current = self._row_to_dict(existing_row)
            shortcut_id = current["id"]

            title = (
                str(data["title"]).strip()
                if "title" in data and data["title"] is not None
                else current["title"]
            )
            if not title:
                raise ValueError("The shortcut title cannot be empty.")

            slug = current["slug"]
            if "slug" in data and data["slug"] is not None and str(data["slug"]).strip():
                candidate_slug = _slugify(str(data["slug"]))
                conflict = self._conn.execute(
                    "SELECT id FROM shortcuts WHERE slug = ? AND id != ? LIMIT 1",
                    (candidate_slug, shortcut_id),
                ).fetchone()
                if conflict is not None:
                    raise ValueError(f"A shortcut with slug '{candidate_slug}' already exists.")
                slug = candidate_slug

            icon = (
                str(data["icon"]).strip() or "⚡"
                if "icon" in data and data["icon"] is not None
                else current["icon"]
            )
            category = (
                self._normalize_category(data["category"])
                if "category" in data and data["category"] is not None
                else current["category"]
            )
            action_type = (
                self._validate_action_type(data["action_type"])
                if "action_type" in data and data["action_type"] is not None
                else current["action_type"]
            )
            payload = (
                self._validate_payload(data["payload"])
                if "payload" in data
                else current["payload"]
            )
            voice_triggers = (
                str(data["voice_triggers"] or "").strip()
                if "voice_triggers" in data
                else current["voice_triggers"]
            )
            color = (
                self._normalize_color(data["color"])
                if "color" in data and data["color"] is not None
                else current["color"]
            )
            pinned_on_deck = (
                bool(data["pinned_on_deck"])
                if "pinned_on_deck" in data and data["pinned_on_deck"] is not None
                else current["pinned_on_deck"]
            )
            sort_order = (
                int(data["sort_order"])
                if "sort_order" in data and data["sort_order"] is not None
                else current["sort_order"]
            )
            requires_confirmation = (
                bool(data["requires_confirmation"])
                if "requires_confirmation" in data
                and data["requires_confirmation"] is not None
                else current["requires_confirmation"]
            )
            updated_at = _now_iso()

            self._conn.execute(
                """
                UPDATE shortcuts
                SET slug = ?, title = ?, icon = ?, category = ?, action_type = ?,
                    payload = ?, voice_triggers = ?, color = ?, pinned_on_deck = ?,
                    sort_order = ?, requires_confirmation = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    slug,
                    title,
                    icon,
                    category,
                    action_type,
                    json.dumps(payload, ensure_ascii=False),
                    voice_triggers,
                    color,
                    1 if pinned_on_deck else 0,
                    sort_order,
                    1 if requires_confirmation else 0,
                    updated_at,
                    shortcut_id,
                ),
            )
            updated_row = self._conn.execute(
                "SELECT * FROM shortcuts WHERE id = ?",
                (shortcut_id,),
            ).fetchone()
            assert updated_row is not None
            return self._row_to_dict(updated_row)

    def delete_shortcut(self, identifier: int | str) -> bool:
        """Remove a shortcut by `id` or `slug` and return `True` if removed."""
        with self._lock, self._conn:
            row = self._get_row_locked(identifier)
            if row is None:
                return False
            self._conn.execute("DELETE FROM shortcuts WHERE id = ?", (int(row["id"]),))
            return True

    def reorder_shortcuts(self, ordered_ids: list[int | str]) -> list[dict[str, Any]]:
        """Reorder the shortcuts following the given sequence of `id` or `slug`."""
        with self._lock, self._conn:
            all_rows = self._conn.execute(
                "SELECT id, slug FROM shortcuts ORDER BY sort_order ASC, id ASC"
            ).fetchall()
            all_ids = [int(row["id"]) for row in all_rows]

            seen: set[int] = set()
            final_order: list[int] = []
            for item in ordered_ids:
                row = self._get_row_locked(item)
                if row is not None:
                    row_id = int(row["id"])
                    if row_id not in seen:
                        seen.add(row_id)
                        final_order.append(row_id)

            for row_id in all_ids:
                if row_id not in seen:
                    seen.add(row_id)
                    final_order.append(row_id)

            now = _now_iso()
            for idx, row_id in enumerate(final_order):
                self._conn.execute(
                    "UPDATE shortcuts SET sort_order = ?, updated_at = ? WHERE id = ?",
                    (idx, now, row_id),
                )

            return self.list_shortcuts()

    def reset_defaults(self) -> list[dict[str, Any]]:
        """Restore the full default shortcut catalog in SQLite."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM shortcuts")
            self._seed_defaults_locked()
        return self.list_shortcuts()

    def find_by_trigger(self, text: str) -> dict[str, Any] | None:
        """Find the best shortcut matching a phrase or voice trigger."""
        query = _normalize_trigger(text)
        if not query:
            return None

        shortcuts = self.list_shortcuts()
        best_score = 0
        best_match: dict[str, Any] | None = None

        for shortcut in shortcuts:
            candidates: list[str] = [
                _normalize_trigger(shortcut["slug"].replace("_", " ")),
                _normalize_trigger(shortcut["title"]),
            ]
            raw_triggers = shortcut.get("voice_triggers") or ""
            for part in raw_triggers.split(","):
                norm_part = _normalize_trigger(part)
                if norm_part:
                    candidates.append(norm_part)

            for cand in candidates:
                if not cand:
                    continue
                if query == cand:
                    # An exact match has top priority; ties are broken by trigger length
                    score = 10_000 + len(cand)
                elif cand in query:
                    score = 1_000 + len(cand)
                elif len(query) >= 4 and query in cand:
                    score = 100 + len(query)
                else:
                    continue

                if score > best_score:
                    best_score = score
                    best_match = shortcut

        return best_match

    def build_agent_shortcuts_prompt(
        self,
        running_apps: list[dict[str, Any]] | None = None,
        max_chars: int = 1800,
    ) -> str:
        """Build a compact summary of shortcuts and open apps for the LLM system prompt."""
        if max_chars <= 0:
            return ""

        apps_line = ""
        if running_apps:
            app_labels: list[str] = []
            for app in running_apps:
                name = str(app.get("name") or "").strip()
                if not name:
                    continue
                if app.get("frontmost"):
                    app_labels.append(f"{name}*")
                elif app.get("running", True):
                    app_labels.append(name)
            if app_labels:
                apps_line = f"Apps abertos ([action:app:<nome>]): {', '.join(app_labels[:12])}"

        shortcuts = self.list_shortcuts()
        header = "Atalhos disponíveis ([action:shortcut:<slug>]):"
        shortcut_lines: list[str] = []
        for item in shortcuts:
            triggers = (item.get("voice_triggers") or "").strip()
            if triggers:
                # Keep up to 2 short triggers so the whole catalog and apps fit in <= 1800 chars
                short_triggers = ", ".join(
                    part.strip() for part in triggers.split(",")[:2] if part.strip()
                )
                entry = f"- [{item['slug']}] {item['title']} ({short_triggers})"
            else:
                entry = f"- [{item['slug']}] {item['title']}"
            shortcut_lines.append(entry)

        # Reserve room for the open-apps line when it fits comfortably
        reserved_for_apps = len(apps_line) + 1 if apps_line and len(apps_line) + len(header) + 2 < max_chars else 0
        shortcut_budget = max_chars - reserved_for_apps

        result_lines: list[str] = []
        current_len = 0
        for line in [header, *shortcut_lines]:
            addition = len(line) + (1 if result_lines else 0)
            if current_len + addition <= shortcut_budget:
                result_lines.append(line)
                current_len += addition
            elif not result_lines:
                return line[:max_chars]
            else:
                break

        if apps_line:
            addition = len(apps_line) + (1 if result_lines else 0)
            if current_len + addition <= max_chars:
                result_lines.append(apps_line)

        return "\n".join(result_lines)

    def close(self) -> None:
        """Close the SQLite connection safely."""
        with self._lock:
            self._conn.close()
