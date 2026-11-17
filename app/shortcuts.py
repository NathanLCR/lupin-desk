"""Armazenamento persistente e catálogo padrão de atalhos configuráveis no SQLite."""

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
    """Retorna timestamp UTC atual em formato ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def _strip_accents(text: str) -> str:
    """Remove acentos mantendo apenas caracteres ASCII base para comparação."""
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _slugify(text: str) -> str:
    """Converte texto livre em slug seguro com letras minúsculas e underscore."""
    ascii_text = _strip_accents(text).lower().strip()
    replaced = re.sub(r"[\s\-/]+", "_", ascii_text)
    cleaned = _SLUG_CLEAN_RE.sub("", replaced).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    return cleaned or "atalho"


def _normalize_trigger(text: str) -> str:
    """Normaliza frase ou gatilho de voz para busca tolerante a acentos e pontuação."""
    plain = _strip_accents(text).lower().strip()
    plain = re.sub(r"[^\w\s]", " ", plain)
    return re.sub(r"\s+", " ", plain).strip()


# Catálogo padrão pré-mapeado para resolver tela externa e Dock escondida no macOS
DEFAULT_SHORTCUTS: tuple[dict[str, Any], ...] = (
    # Espaços & Janelas
    {
        "slug": "mission_control",
        "title": "Mission Control",
        "icon": "🪟",
        "category": "spaces",
        "action_type": "mac_command",
        "payload": {"command": "mission_control"},
        "voice_triggers": "mission control, ver todas as janelas, visao geral, workspaces",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "app_expose",
        "title": "Exposé do App",
        "icon": "🗂️",
        "category": "spaces",
        "action_type": "mac_command",
        "payload": {"command": "app_expose"},
        "voice_triggers": "expose, expose do app, janelas do app, app expose",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "space_left",
        "title": "Espaço ⬅️",
        "icon": "⬅️",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "ctrl+left"},
        "voice_triggers": "espaco esquerda, espaco anterior, space left, desktop esquerda",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "space_right",
        "title": "Espaço ➡️",
        "icon": "➡️",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "ctrl+right"},
        "voice_triggers": "espaco direita, proximo espaco, space right, desktop direita",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "switch_window",
        "title": "Trocar Janela",
        "icon": "🔁",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+grave"},
        "voice_triggers": "trocar janela, proxima janela do app, switch window",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    {
        "slug": "switch_app",
        "title": "Alternar App",
        "icon": "🔀",
        "category": "apps",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+tab"},
        "voice_triggers": "alternar app, trocar app, app anterior, switch app",
        "color": "violet",
        "pinned_on_deck": True,
    },
    {
        "slug": "fullscreen_window",
        "title": "Tela Cheia",
        "icon": "⛶",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "ctrl+cmd+f"},
        "voice_triggers": "tela cheia, fullscreen, maximizar janela",
        "color": "cyan",
        "pinned_on_deck": False,
    },
    {
        "slug": "toggle_dock",
        "title": "Mostrar/Ocultar Dock",
        "icon": "🧭",
        "category": "spaces",
        "action_type": "keystroke",
        "payload": {"keys": "opt+cmd+d"},
        "voice_triggers": "mostrar dock, ocultar dock, alternar dock, toggle dock",
        "color": "cyan",
        "pinned_on_deck": True,
    },
    # Captura / Prints
    {
        "slug": "screenshot_clipboard",
        "title": "Print Seleção → Clipboard",
        "icon": "📋",
        "category": "capture",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+ctrl+shift+4"},
        "voice_triggers": "print clipboard, print selecao clipboard, captura para clipboard, screenshot clipboard",
        "color": "amber",
        "pinned_on_deck": True,
    },
    {
        "slug": "screenshot_file",
        "title": "Print Seleção → Arquivo",
        "icon": "📸",
        "category": "capture",
        "action_type": "mac_command",
        "payload": {"command": "screenshot_area_file"},
        "voice_triggers": "print arquivo, print selecao arquivo, tirar print, screenshot file",
        "color": "amber",
        "pinned_on_deck": True,
    },
    {
        "slug": "screenshot_full",
        "title": "Print Tela Inteira",
        "icon": "🖼️",
        "category": "capture",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+shift+3"},
        "voice_triggers": "print tela inteira, captura tela inteira, screenshot full",
        "color": "amber",
        "pinned_on_deck": False,
    },
    # Edição & Busca ("Sem Decorar")
    {
        "slug": "find",
        "title": "Pesquisar",
        "icon": "🔍",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+f"},
        "voice_triggers": "pesquisar, buscar na pagina, procurar, find",
        "color": "emerald",
        "pinned_on_deck": True,
    },
    {
        "slug": "find_replace",
        "title": "Pesquisar e Substituir",
        "icon": "🔄",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+opt+f"},
        "voice_triggers": "pesquisar e substituir, substituir, find and replace",
        "color": "emerald",
        "pinned_on_deck": True,
    },
    {
        "slug": "paste_plain",
        "title": "Colar Sem Formatação",
        "icon": "📄",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "opt+cmd+shift+v"},
        "voice_triggers": "colar sem formatacao, colar limpo, paste plain",
        "color": "emerald",
        "pinned_on_deck": True,
    },
    {
        "slug": "undo",
        "title": "Desfazer",
        "icon": "↩️",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+z"},
        "voice_triggers": "desfazer, voltar acao, undo",
        "color": "emerald",
        "pinned_on_deck": True,
    },
    {
        "slug": "redo",
        "title": "Refazer",
        "icon": "↪️",
        "category": "editing",
        "action_type": "keystroke",
        "payload": {"keys": "cmd+shift+z"},
        "voice_triggers": "refazer, avancar acao, redo",
        "color": "emerald",
        "pinned_on_deck": False,
    },
    # Mídia & Sistema & Foco
    {
        "slug": "play_pause",
        "title": "Play / Pause",
        "icon": "⏯️",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "play_pause"},
        "voice_triggers": "play pause, pausar musica, tocar musica, retomar musica",
        "color": "rose",
        "pinned_on_deck": True,
    },
    {
        "slug": "next_track",
        "title": "Próxima Faixa",
        "icon": "⏭️",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "next_track"},
        "voice_triggers": "proxima faixa, proxima musica, pular musica, next track",
        "color": "rose",
        "pinned_on_deck": True,
    },
    {
        "slug": "prev_track",
        "title": "Faixa Anterior",
        "icon": "⏮️",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "prev_track"},
        "voice_triggers": "faixa anterior, musica anterior, voltar musica, prev track",
        "color": "rose",
        "pinned_on_deck": False,
    },
    {
        "slug": "volume_up",
        "title": "Volume +",
        "icon": "🔊",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "volume_up"},
        "voice_triggers": "aumentar volume, subir volume, volume mais, volume up",
        "color": "rose",
        "pinned_on_deck": True,
    },
    {
        "slug": "volume_down",
        "title": "Volume -",
        "icon": "🔉",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "volume_down"},
        "voice_triggers": "diminuir volume, abaixar volume, volume menos, volume down",
        "color": "rose",
        "pinned_on_deck": True,
    },
    {
        "slug": "volume_mute",
        "title": "Mudo",
        "icon": "🔇",
        "category": "media",
        "action_type": "mac_command",
        "payload": {"command": "volume_mute"},
        "voice_triggers": "mudo, mutar, silenciar som, mute",
        "color": "rose",
        "pinned_on_deck": False,
    },
    {
        "slug": "lock_screen",
        "title": "Bloquear Tela",
        "icon": "🔒",
        "category": "apps",
        "action_type": "mac_command",
        "payload": {"command": "lock_screen"},
        "voice_triggers": "bloquear tela, travar mac, lock screen",
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
        "voice_triggers": "pomodoro, iniciar pomodoro, foco 25 minutos",
        "color": "amber",
        "pinned_on_deck": True,
    },
)


class ShortcutStore:
    """CRUD persistente de atalhos configuráveis e catálogo padrão no SQLite."""

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
        """Cria a tabela `shortcuts`, aplica pragmas e popula seed inicial se vazia."""
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

                # Migração defensiva caso outra instância tenha criado tabela parcial
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

    def _seed_defaults_locked(self) -> None:
        """Popula os atalhos padrão na tabela (requer lock e transação ativos)."""
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
        """Converte uma linha SQLite em dicionário tipado com `payload` desserializado."""
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
        """Valida e normaliza `payload` como dicionário JSON."""
        if payload is None:
            return {}
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ValueError("Payload JSON inválido.") from exc
            payload = parsed
        if not isinstance(payload, dict):
            raise ValueError("Payload do atalho deve ser um objeto JSON.")
        return dict(payload)

    @staticmethod
    def _validate_action_type(action_type: Any) -> str:
        """Valida se `action_type` pertence ao conjunto suportado."""
        cleaned = str(action_type or "").strip()
        if cleaned not in VALID_ACTION_TYPES:
            raise ValueError(
                f"action_type inválido: '{cleaned}'. Permitidos: {sorted(VALID_ACTION_TYPES)}"
            )
        return cleaned

    @staticmethod
    def _normalize_category(category: Any) -> str:
        """Normaliza categoria com fallback seguro para `custom`."""
        cleaned = str(category or "").strip().lower()
        if not cleaned:
            return "custom"
        if cleaned == "focus":
            return "custom"
        if cleaned not in VALID_CATEGORIES:
            raise ValueError(
                f"Categoria inválida: '{cleaned}'. Permitidas: {sorted(VALID_CATEGORIES)}"
            )
        return cleaned

    @staticmethod
    def _normalize_color(color: Any) -> str:
        """Normaliza cor do tile com fallback para `cyan`."""
        cleaned = str(color or "cyan").strip().lower()
        return cleaned if cleaned in VALID_COLORS else "cyan"

    def _generate_unique_slug_locked(self, base_text: str) -> str:
        """Gera slug único evitando colisões na tabela `shortcuts`."""
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
        """Busca linha por `id` inteiro ou `slug` textual."""
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
        """Lista todos os atalhos ordenados por `sort_order` e `id`, opcionalmente filtrados."""
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
        """Obtém um atalho por `id` numérico ou `slug`."""
        with self._lock:
            row = self._get_row_locked(identifier)
            return self._row_to_dict(row) if row is not None else None

    def create_shortcut(self, data: dict[str, Any]) -> dict[str, Any]:
        """Cria um novo atalho validando `action_type` e gerando `slug` único se omitido."""
        if not isinstance(data, dict):
            raise ValueError("Dados do atalho devem ser um dicionário.")

        title = str(data.get("title") or "").strip()
        if not title:
            raise ValueError("O título do atalho é obrigatório.")

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
                    raise ValueError(f"Já existe um atalho com o slug '{slug}'.")
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
        """Atualiza campos de um atalho existente identificado por `id` ou `slug`."""
        if not isinstance(data, dict):
            raise ValueError("Dados de atualização devem ser um dicionário.")

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
                raise ValueError("O título do atalho não pode ficar vazio.")

            slug = current["slug"]
            if "slug" in data and data["slug"] is not None and str(data["slug"]).strip():
                candidate_slug = _slugify(str(data["slug"]))
                conflict = self._conn.execute(
                    "SELECT id FROM shortcuts WHERE slug = ? AND id != ? LIMIT 1",
                    (candidate_slug, shortcut_id),
                ).fetchone()
                if conflict is not None:
                    raise ValueError(f"Já existe um atalho com o slug '{candidate_slug}'.")
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
        """Remove um atalho por `id` ou `slug` e retorna `True` se removido."""
        with self._lock, self._conn:
            row = self._get_row_locked(identifier)
            if row is None:
                return False
            self._conn.execute("DELETE FROM shortcuts WHERE id = ?", (int(row["id"]),))
            return True

    def reorder_shortcuts(self, ordered_ids: list[int | str]) -> list[dict[str, Any]]:
        """Reordena os atalhos conforme a sequência de `id` ou `slug` fornecida."""
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
        """Restaura o catálogo padrão completo de atalhos no SQLite."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM shortcuts")
            self._seed_defaults_locked()
        return self.list_shortcuts()

    def find_by_trigger(self, text: str) -> dict[str, Any] | None:
        """Encontra o melhor atalho correspondente a uma frase ou gatilho de voz."""
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
                    # Match exato tem prioridade máxima; desempata pelo tamanho do gatilho
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
        """Monta resumo compacto de atalhos e apps abertos para o system prompt do LLM."""
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
                # Mantém até 2 gatilhos curtos para caber todo o catálogo e apps em <= 1800 chars
                short_triggers = ", ".join(
                    part.strip() for part in triggers.split(",")[:2] if part.strip()
                )
                entry = f"- [{item['slug']}] {item['title']} ({short_triggers})"
            else:
                entry = f"- [{item['slug']}] {item['title']}"
            shortcut_lines.append(entry)

        # Reserva espaço para a linha de apps abertos quando ela couber com folga
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
        """Fecha a conexão SQLite com segurança."""
        with self._lock:
            self._conn.close()
