"""Persistent cognitive memory in SQLite (short term, long term, summary and pet state)."""

from __future__ import annotations

import math
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app import speech_pt_br as speech
from app.config import BASE_DIR

_DEFAULT_DB_PATH = BASE_DIR / "data" / "memory.db"

# Fact tags explicitly emitted by the LLM in the raw text
_LLM_FACT_TAG_RE = re.compile(r"\[fact\s*:\s*([^\]]+)\]", re.IGNORECASE)

# Patterns that identify single-attribute facts (they update instead of duplicating).
# They match stored fact text and user speech, so they stay Portuguese/English.
_NAME_KEY_RE = re.compile(
    r"^(?:(?:o|a)\s+)?(?:nome(?:\s+do\s+usu[aá]rio)?|chama-se|se\s+chama|"
    r"usu[aá]rio\s+se\s+chama|apelido|user\s*name|name)\b(?:\s*[:=]\s*|\s+[eé]\s+|\s+)",
    re.IGNORECASE,
)
_LOCATION_KEY_RE = re.compile(
    r"^(?:(?:o|a)\s+)?(?:usu[aá]rio\s+)?(?:mora\s+em|vive\s+em|cidade|"
    r"localiza[çc][aã]o|lives\s+in|city|location)\b(?:\s*[:=]\s*|\s+)",
    re.IGNORECASE,
)

# Heuristic patterns (pt-BR and EN) that capture explicit facts from the user's speech.
# The regexes parse user input and the templates build the stored fact text, so both stay
# Portuguese: stored facts and the consolidation signatures below depend on these exact words.
_HEURISTIC_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"(?:^|\b)(?:meu\s+nome\s+[ée]|me\s+chamo|pode\s+me\s+chamar\s+de|"
            r"my\s+name\s+is|call\s+me)\s+([^.!?\n,;]+)",
            re.IGNORECASE,
        ),
        "identity",
        "Nome do usuário: {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)(?<!n[aã]o\s)(?:eu\s+)?prefiro\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "preference",
        "Prefere {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)i\s+prefer\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "preference",
        "Prefere {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)(?<!n[aã]o\s)(?:eu\s+)?gosto(?:\s+muito)?\s+de\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "preference",
        "Gosta de {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)(?<!don't\s)(?<!do not\s)i\s+like\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "preference",
        "Gosta de {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)(?:eu\s+)?trabalho\s+com\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "work",
        "Trabalha com {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)(?:eu\s+)?trabalho\s+como\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "work",
        "Trabalha como {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)i\s+work\s+(?:with|as)\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "work",
        "Trabalha com/como {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)(?:eu\s+)?moro\s+em\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "location",
        "Mora em {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)i\s+live\s+in\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "location",
        "Mora em {value}",
    ),
    (
        re.compile(
            r"(?:^|\b)(?:eu\s+)?tenho\s+(um|uma)\s+([^.!?\n;]+)",
            re.IGNORECASE,
        ),
        "general",
        "Tem {article} {value}",
    ),
)

_IGNORED_POSSESSION_NOUNS = {
    "duvida",
    "dúvida",
    "pergunta",
    "ideia",
    "idéia",
    "problema",
    "questao",
    "questão",
    "certeza",
    "medo",
    "sono",
    "fome",
    "sede",
    "pressa",
}

_STOPWORDS = {
    "a",
    "o",
    "as",
    "os",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "e",
    "em",
    "um",
    "uma",
    "que",
    "com",
    "para",
    "por",
    "no",
    "na",
    "nos",
    "nas",
    "se",
    "eu",
    "me",
    "meu",
    "minha",
    "voce",
    "você",
    "the",
    "is",
    "in",
    "to",
    "of",
    "and",
}


def _now_utc() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    """Return the current UTC timestamp in ISO-8601 format."""
    return _now_utc().isoformat()


def _parse_iso_utc(raw: str | None) -> datetime:
    """Convert an ISO-8601 string to a UTC datetime, safely falling back to now."""
    if not raw:
        return _now_utc()
    try:
        parsed = datetime.fromisoformat(raw)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return _now_utc()


def _clamp(value: float, minimum: float, maximum: float) -> float:
    """Clamp a numeric value to the range `[minimum, maximum]`."""
    return max(minimum, min(maximum, value))


def _strip_accents(text: str) -> str:
    """Strip accents, keeping only base characters, to normalize keys."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _clean_whitespace(text: str) -> str:
    """Collapse repeated whitespace and trim both ends."""
    return " ".join(text.strip().split())


def _tokenize_plain(text: str) -> list[str]:
    """Extract accent-free normalized alphanumeric tokens for search and comparison."""
    plain = _strip_accents(text).lower()
    tokens = re.findall(r"[a-z0-9]{2,}", plain)
    return [tok for tok in tokens if tok not in _STOPWORDS]


def _normalize_fact_key(fact: str, category: str = "general") -> str:
    """Generate a normalized key to deduplicate and update similar facts."""
    cleaned = _clean_whitespace(fact)
    plain = _strip_accents(cleaned).lower().rstrip(".,;!?")

    if category == "name" or _NAME_KEY_RE.match(cleaned):
        return "attr:name"

    if _LOCATION_KEY_RE.match(cleaned):
        return "attr:location"

    if ":" in plain:
        prefix, _, _rest = plain.partition(":")
        prefix_clean = _clean_whitespace(prefix)
        words = prefix_clean.split()
        if 1 <= len(words) <= 4 and len(prefix_clean) <= 35:
            return f"prefix:{prefix_clean}"

    return f"fact:{plain}"


def _consolidation_signature(fact: str, category: str = "general") -> str:
    """Compute a semantic signature to group duplicate or contradictory facts."""
    cleaned = _clean_whitespace(fact)
    plain = _strip_accents(cleaned).lower().rstrip(".,;!?")
    plain = re.sub(r"^(?:o\s+|a\s+)?(?:usuario|user)\s+", "", plain)

    key = _normalize_fact_key(cleaned, category)
    if key.startswith("attr:") or key.startswith("prefix:"):
        return key

    # Detect direct polarity contradictions (e.g. "Gosta de café" vs "Não gosta de café").
    negated = re.sub(r"^(?:nao|nunca|jamais|don't|do not|does not)\s+", "", plain)
    if negated != plain:
        return f"polarity:{negated}"

    # Detect exclusive theme/style contradictions (e.g. "Prefere tema claro" vs "Prefere tema escuro").
    for exclusive_prefix in ("prefere tema ", "trabalha como ", "mora em ", "chama-se "):
        if plain.startswith(exclusive_prefix):
            return f"slot:{exclusive_prefix.strip()}"

    if re.match(r"^(?:gosta\s+de|prefere|usa|trabalha\s+com)\s+", plain):
        return f"polarity:{plain}"

    return f"exact:{plain}"


def _infer_category(fact_text: str) -> str:
    """Infer a simple category for facts extracted from a tag without an explicit category."""
    plain = _strip_accents(fact_text).lower()
    if _NAME_KEY_RE.match(fact_text):
        return "identity"
    if _LOCATION_KEY_RE.match(fact_text):
        return "location"
    if any(token in plain for token in ("prefere", "gosta", "favorit", "prefer", "like")):
        return "preference"
    if any(token in plain for token in ("trabalha", "profiss", "emprego", "work", "job")):
        return "work"
    return "general"


def _split_clauses(user_text: str) -> list[str]:
    """Split the user text into short clauses for safe extraction."""
    raw_sentences = re.split(r"[.\n;!]+", user_text)
    clauses: list[str] = []
    connector_re = re.compile(
        r"(?:,\s*(?:e\s+)?|\s+e\s+)(?=(?:eu|meu|me|pode|moro|trabalho|tenho|prefiro|gosto)\b)",
        re.IGNORECASE,
    )
    for sentence in raw_sentences:
        stripped = sentence.strip()
        if not stripped or stripped.endswith("?"):
            continue
        sub_parts = connector_re.split(stripped)
        for part in sub_parts:
            part_clean = part.strip(" ,")
            if part_clean and not part_clean.endswith("?"):
                clauses.append(part_clean)
    return clauses


def _derive_mood_label(pleasure: float, arousal: float, energy: float) -> str:
    """Translate affective dimensions and energy into a (pt-BR) mood label."""
    if energy < 25.0:
        return speech.MOOD_SLEEPY
    if pleasure >= 0.45 and arousal >= 0.25:
        return speech.MOOD_EXCITED
    if pleasure >= 0.35:
        return speech.MOOD_HAPPY
    if pleasure >= 0.1:
        return speech.MOOD_CALM
    if pleasure <= -0.35 and arousal >= 0.2:
        return speech.MOOD_IRRITATED
    if pleasure <= -0.2:
        return speech.MOOD_NEEDY
    return speech.MOOD_NEUTRAL


class MemoryStore:
    """SQLite cognitive storage (short term, long term, summary and pet mood)."""

    def __init__(
        self,
        db_path: Path | str | None = None,
        max_short_term_messages: int = 10,
        max_user_facts: int = 25,
    ) -> None:
        self._is_in_memory = str(db_path) == ":memory:"
        if db_path is None:
            resolved_path: Path | str = _DEFAULT_DB_PATH
        elif self._is_in_memory:
            resolved_path = ":memory:"
        else:
            resolved_path = Path(db_path)

        self.db_path = resolved_path
        self.max_short_term_messages = max(1, int(max_short_term_messages))
        self.max_user_facts = max(1, int(max_user_facts))
        self._lock = threading.RLock()
        self._fts_enabled = False

        if not self._is_in_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Enable WAL/integrity, create tables and migrate new columns idempotently."""
        now_iso = _now_iso()
        with self._lock:
            if not self._is_in_memory:
                self._conn.execute("PRAGMA journal_mode=WAL;")
                self._conn.execute("PRAGMA synchronous=NORMAL;")
            self._conn.execute("PRAGMA busy_timeout=5000;")

            with self._conn:
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        role TEXT NOT NULL,
                        content TEXT NOT NULL,
                        emotion TEXT,
                        created_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS user_facts (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        category TEXT NOT NULL,
                        fact TEXT NOT NULL,
                        normalized_key TEXT NOT NULL UNIQUE,
                        updated_at TEXT NOT NULL,
                        pinned INTEGER NOT NULL DEFAULT 0,
                        importance INTEGER NOT NULL DEFAULT 5,
                        access_count INTEGER NOT NULL DEFAULT 1,
                        last_accessed TEXT,
                        superseded_by INTEGER
                    )
                    """
                )

                # Idempotent migration for databases created in Phase 1.
                existing_cols = {
                    str(row["name"])
                    for row in self._conn.execute("PRAGMA table_info(user_facts)").fetchall()
                }
                migrations: tuple[tuple[str, str], ...] = (
                    ("pinned", "ALTER TABLE user_facts ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"),
                    (
                        "importance",
                        "ALTER TABLE user_facts ADD COLUMN importance INTEGER NOT NULL DEFAULT 5",
                    ),
                    (
                        "access_count",
                        "ALTER TABLE user_facts ADD COLUMN access_count INTEGER NOT NULL DEFAULT 1",
                    ),
                    ("last_accessed", "ALTER TABLE user_facts ADD COLUMN last_accessed TEXT"),
                    ("superseded_by", "ALTER TABLE user_facts ADD COLUMN superseded_by INTEGER"),
                )
                for col_name, alter_sql in migrations:
                    if col_name not in existing_cols:
                        self._conn.execute(alter_sql)

                self._conn.execute(
                    """
                    UPDATE user_facts
                    SET last_accessed = updated_at
                    WHERE last_accessed IS NULL
                    """
                )

                # Rolling summary state (intermediate layer for old messages).
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS rolling_state (
                        id INTEGER PRIMARY KEY CHECK(id=1),
                        summary TEXT NOT NULL DEFAULT '',
                        updated_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO rolling_state (id, summary, updated_at)
                    VALUES (1, '', ?)
                    """,
                    (now_iso,),
                )

                # Persistent emotional state of the pet.
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS companion_state (
                        id INTEGER PRIMARY KEY CHECK(id=1),
                        pleasure REAL NOT NULL DEFAULT 0.2,
                        arousal REAL NOT NULL DEFAULT 0.0,
                        energy REAL NOT NULL DEFAULT 85.0,
                        affinity REAL NOT NULL DEFAULT 50.0,
                        last_interaction_at TEXT NOT NULL
                    )
                    """
                )
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO companion_state (
                        id, pleasure, arousal, energy, affinity, last_interaction_at
                    )
                    VALUES (1, 0.2, 0.0, 85.0, 50.0, ?)
                    """,
                    (now_iso,),
                )

                # Lightweight application metadata (e.g. date of the last First Wake).
                self._conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_meta (
                        key TEXT PRIMARY KEY,
                        value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                    """
                )

                # FTS5 index for fast text search, with a safe fallback when unavailable.
                try:
                    self._conn.execute(
                        """
                        CREATE VIRTUAL TABLE IF NOT EXISTS user_facts_fts USING fts5(
                            fact,
                            category,
                            tokenize='unicode61 remove_diacritics 2'
                        )
                        """
                    )
                    self._fts_enabled = True
                    self._rebuild_fts_locked()
                except sqlite3.OperationalError:
                    self._fts_enabled = False

    def _rebuild_fts_locked(self) -> None:
        """Sync the FTS5 index with every active fact in `user_facts`."""
        if not self._fts_enabled:
            return
        self._conn.execute("DELETE FROM user_facts_fts")
        rows = self._conn.execute(
            """
            SELECT id, fact, category
            FROM user_facts
            WHERE superseded_by IS NULL
            """
        ).fetchall()
        if rows:
            self._conn.executemany(
                "INSERT INTO user_facts_fts (rowid, fact, category) VALUES (?, ?, ?)",
                [(int(r["id"]), str(r["fact"]), str(r["category"])) for r in rows],
            )

    def _sync_fts_row_locked(self, fact_id: int, fact: str, category: str) -> None:
        """Update a single record in the FTS5 index."""
        if not self._fts_enabled:
            return
        self._conn.execute("DELETE FROM user_facts_fts WHERE rowid = ?", (fact_id,))
        self._conn.execute(
            "INSERT INTO user_facts_fts (rowid, fact, category) VALUES (?, ?, ?)",
            (fact_id, fact, category),
        )

    def _delete_fts_row_locked(self, fact_id: int) -> None:
        """Remove a record from the FTS5 index."""
        if not self._fts_enabled:
            return
        self._conn.execute("DELETE FROM user_facts_fts WHERE rowid = ?", (fact_id,))

    @staticmethod
    def _row_to_fact(row: sqlite3.Row) -> dict[str, Any]:
        """Convert a `user_facts` SQLite row into a serializable dict."""
        superseded_raw = row["superseded_by"]
        return {
            "id": int(row["id"]),
            "category": str(row["category"]),
            "fact": str(row["fact"]),
            "updated_at": str(row["updated_at"]),
            "pinned": bool(row["pinned"]),
            "importance": int(row["importance"]),
            "access_count": int(row["access_count"]),
            "last_accessed": str(row["last_accessed"] or row["updated_at"]),
            "superseded_by": int(superseded_raw) if superseded_raw is not None else None,
        }

    def close(self) -> None:
        """Close the SQLite connection safely."""
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Layer 1: Short term (sliding window of messages)
    # ------------------------------------------------------------------

    def add_message(
        self,
        role: str,
        content: str,
        emotion: str | None = None,
    ) -> int:
        """Record a message in short-term memory and return its ID."""
        cleaned_role = role.strip() or "user"
        created_at = _now_iso()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                INSERT INTO messages (role, content, emotion, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (cleaned_role, content, emotion, created_at),
            )
            return int(cursor.lastrowid)

    def get_recent_messages(self, limit: int | None = None) -> list[dict[str, str]]:
        """Return the latest messages in chronological order without inflating the context."""
        effective_limit = self.max_short_term_messages if limit is None else int(limit)
        if effective_limit <= 0:
            return []

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT role, content
                FROM messages
                ORDER BY id DESC
                LIMIT ?
                """,
                (effective_limit,),
            ).fetchall()

        return [{"role": str(row["role"]), "content": str(row["content"])} for row in reversed(rows)]

    def get_recent_messages_count(self) -> int:
        """Return how many messages are currently stored in layer 1."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS total FROM messages").fetchone()
        return int(row["total"]) if row is not None else 0

    # ------------------------------------------------------------------
    # Intermediate layer: Rolling Summary
    # ------------------------------------------------------------------

    def get_rolling_summary(self) -> str:
        """Return the current rolling summary of old messages."""
        with self._lock:
            row = self._conn.execute(
                "SELECT summary FROM rolling_state WHERE id = 1"
            ).fetchone()
        return str(row["summary"]).strip() if row is not None else ""

    def update_rolling_summary(self, summary: str) -> str:
        """Update and persist the conversation rolling summary."""
        cleaned = _clean_whitespace(summary)
        now_iso = _now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO rolling_state (id, summary, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (cleaned, now_iso),
            )
        return cleaned

    # ------------------------------------------------------------------
    # Layer 2: Long term (profile, Core Memory and learned facts)
    # ------------------------------------------------------------------

    def add_fact(
        self,
        fact: str,
        category: str = "general",
        pinned: bool | None = None,
        importance: int | None = None,
    ) -> dict[str, Any]:
        """Add or update a deduplicated fact, protecting `pinned=True` facts from eviction."""
        cleaned_fact = _clean_whitespace(fact)
        if not cleaned_fact:
            raise ValueError("The fact cannot be empty.")

        cleaned_category = _clean_whitespace(category).lower() or "general"
        normalized_key = _normalize_fact_key(cleaned_fact, cleaned_category)
        updated_at = _now_iso()

        insert_pinned = 1 if pinned is True else 0
        insert_importance = (
            max(1, min(10, int(importance))) if importance is not None else 5
        )

        with self._lock, self._conn:
            if pinned is None and importance is None:
                self._conn.execute(
                    """
                    INSERT INTO user_facts (
                        category, fact, normalized_key, updated_at,
                        pinned, importance, access_count, last_accessed, superseded_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL)
                    ON CONFLICT(normalized_key) DO UPDATE SET
                        category = excluded.category,
                        fact = excluded.fact,
                        updated_at = excluded.updated_at,
                        access_count = user_facts.access_count + 1,
                        last_accessed = excluded.last_accessed,
                        superseded_by = NULL
                    """,
                    (
                        cleaned_category,
                        cleaned_fact,
                        normalized_key,
                        updated_at,
                        insert_pinned,
                        insert_importance,
                        updated_at,
                    ),
                )
            elif pinned is not None and importance is None:
                self._conn.execute(
                    """
                    INSERT INTO user_facts (
                        category, fact, normalized_key, updated_at,
                        pinned, importance, access_count, last_accessed, superseded_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL)
                    ON CONFLICT(normalized_key) DO UPDATE SET
                        category = excluded.category,
                        fact = excluded.fact,
                        updated_at = excluded.updated_at,
                        pinned = excluded.pinned,
                        access_count = user_facts.access_count + 1,
                        last_accessed = excluded.last_accessed,
                        superseded_by = NULL
                    """,
                    (
                        cleaned_category,
                        cleaned_fact,
                        normalized_key,
                        updated_at,
                        insert_pinned,
                        insert_importance,
                        updated_at,
                    ),
                )
            elif pinned is None and importance is not None:
                self._conn.execute(
                    """
                    INSERT INTO user_facts (
                        category, fact, normalized_key, updated_at,
                        pinned, importance, access_count, last_accessed, superseded_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL)
                    ON CONFLICT(normalized_key) DO UPDATE SET
                        category = excluded.category,
                        fact = excluded.fact,
                        updated_at = excluded.updated_at,
                        importance = excluded.importance,
                        access_count = user_facts.access_count + 1,
                        last_accessed = excluded.last_accessed,
                        superseded_by = NULL
                    """,
                    (
                        cleaned_category,
                        cleaned_fact,
                        normalized_key,
                        updated_at,
                        insert_pinned,
                        insert_importance,
                        updated_at,
                    ),
                )
            else:
                self._conn.execute(
                    """
                    INSERT INTO user_facts (
                        category, fact, normalized_key, updated_at,
                        pinned, importance, access_count, last_accessed, superseded_by
                    )
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, NULL)
                    ON CONFLICT(normalized_key) DO UPDATE SET
                        category = excluded.category,
                        fact = excluded.fact,
                        updated_at = excluded.updated_at,
                        pinned = excluded.pinned,
                        importance = excluded.importance,
                        access_count = user_facts.access_count + 1,
                        last_accessed = excluded.last_accessed,
                        superseded_by = NULL
                    """,
                    (
                        cleaned_category,
                        cleaned_fact,
                        normalized_key,
                        updated_at,
                        insert_pinned,
                        insert_importance,
                        updated_at,
                    ),
                )

            saved = self._conn.execute(
                """
                SELECT id, category, fact, updated_at, pinned, importance,
                       access_count, last_accessed, superseded_by
                FROM user_facts
                WHERE normalized_key = ?
                """,
                (normalized_key,),
            ).fetchone()
            assert saved is not None
            saved_id = int(saved["id"])
            self._sync_fts_row_locked(saved_id, str(saved["fact"]), str(saved["category"]))

            # Remove the oldest unpinned facts when the active total exceeds `max_user_facts`.
            active_count_row = self._conn.execute(
                "SELECT COUNT(*) AS total FROM user_facts WHERE superseded_by IS NULL"
            ).fetchone()
            active_count = int(active_count_row["total"]) if active_count_row is not None else 0
            if active_count > self.max_user_facts:
                excess = active_count - self.max_user_facts
                overflow_rows = self._conn.execute(
                    """
                    SELECT id
                    FROM user_facts
                    WHERE pinned = 0 AND superseded_by IS NULL
                    ORDER BY updated_at ASC, id ASC
                    LIMIT ?
                    """,
                    (excess,),
                ).fetchall()
                if overflow_rows:
                    ids_to_delete = [int(row["id"]) for row in overflow_rows]
                    self._conn.executemany(
                        "DELETE FROM user_facts WHERE id = ?",
                        [(fid,) for fid in ids_to_delete],
                    )
                    for fid in ids_to_delete:
                        self._delete_fts_row_locked(fid)

        return self._row_to_fact(saved)

    def get_facts(self, include_superseded: bool = False) -> list[dict[str, Any]]:
        """List learned facts, pinned first and then the most recent."""
        where_clause = "" if include_superseded else "WHERE superseded_by IS NULL"
        with self._lock:
            rows = self._conn.execute(
                f"""
                SELECT id, category, fact, updated_at, pinned, importance,
                       access_count, last_accessed, superseded_by
                FROM user_facts
                {where_clause}
                ORDER BY pinned DESC, updated_at DESC, id DESC
                """
            ).fetchall()

        return [self._row_to_fact(row) for row in rows]

    def set_fact_pinned(self, fact_id: int, pinned: bool) -> dict[str, Any] | None:
        """Pin or unpin a fact in Core Memory (pinned facts are never evicted)."""
        now_iso = _now_iso()
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE user_facts
                SET pinned = ?, last_accessed = ?
                WHERE id = ?
                """,
                (1 if pinned else 0, now_iso, int(fact_id)),
            )
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute(
                """
                SELECT id, category, fact, updated_at, pinned, importance,
                       access_count, last_accessed, superseded_by
                FROM user_facts
                WHERE id = ?
                """,
                (int(fact_id),),
            ).fetchone()
        return self._row_to_fact(row) if row is not None else None

    def update_fact_importance(self, fact_id: int, importance: int) -> dict[str, Any] | None:
        """Update the importance (`1..10`) of a specific fact."""
        clamped = max(1, min(10, int(importance)))
        with self._lock, self._conn:
            cursor = self._conn.execute(
                """
                UPDATE user_facts
                SET importance = ?
                WHERE id = ?
                """,
                (clamped, int(fact_id)),
            )
            if cursor.rowcount == 0:
                return None
            row = self._conn.execute(
                """
                SELECT id, category, fact, updated_at, pinned, importance,
                       access_count, last_accessed, superseded_by
                FROM user_facts
                WHERE id = ?
                """,
                (int(fact_id),),
            ).fetchone()
        return self._row_to_fact(row) if row is not None else None

    def delete_fact(self, fact_id: int) -> bool:
        """Delete a fact by ID and report whether any record was removed."""
        target_id = int(fact_id)
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM user_facts WHERE id = ?",
                (target_id,),
            )
            self._delete_fts_row_locked(target_id)
            return cursor.rowcount > 0

    def consolidate_facts(self) -> int:
        """Consolidate duplicate or contradictory facts by setting `superseded_by`."""
        with self._lock, self._conn:
            rows = self._conn.execute(
                """
                SELECT id, category, fact, updated_at, pinned, importance
                FROM user_facts
                WHERE superseded_by IS NULL
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()

            if len(rows) < 2:
                return 0

            groups: dict[str, list[sqlite3.Row]] = {}
            for row in rows:
                sig = _consolidation_signature(str(row["fact"]), str(row["category"]))
                groups.setdefault(sig, []).append(row)

            consolidated_count = 0
            for group_rows in groups.values():
                if len(group_rows) < 2:
                    continue

                # Keep the most recent fact as the winner and preserve pin/importance status.
                winner = group_rows[0]
                winner_id = int(winner["id"])
                max_pinned = max(int(r["pinned"]) for r in group_rows)
                max_importance = max(int(r["importance"]) for r in group_rows)

                if max_pinned != int(winner["pinned"]) or max_importance != int(winner["importance"]):
                    self._conn.execute(
                        """
                        UPDATE user_facts
                        SET pinned = ?, importance = ?
                        WHERE id = ?
                        """,
                        (max_pinned, max_importance, winner_id),
                    )

                for loser in group_rows[1:]:
                    loser_id = int(loser["id"])
                    self._conn.execute(
                        "UPDATE user_facts SET superseded_by = ? WHERE id = ?",
                        (winner_id, loser_id),
                    )
                    self._delete_fts_row_locked(loser_id)
                    consolidated_count += 1

            return consolidated_count

    def extract_and_store_facts(
        self,
        user_text: str,
        assistant_raw_text: str,
    ) -> list[dict[str, Any]]:
        """Extract facts from the LLM `[fact: ...]` tags and explicit user heuristics."""
        stored_by_id: dict[int, dict[str, Any]] = {}

        # 1) Explicit heuristic facts present in the user message (pt-BR / EN).
        for clause in _split_clauses(user_text):
            for pattern, category, template in _HEURISTIC_RULES:
                match = pattern.search(clause)
                if not match:
                    continue

                if "{article}" in template:
                    article = match.group(1).lower()
                    raw_value = _clean_whitespace(match.group(2))
                    first_word = _strip_accents(raw_value.split(" ", 1)[0].lower()) if raw_value else ""
                    if not raw_value or first_word in _IGNORED_POSSESSION_NOUNS:
                        continue
                    candidate = template.format(article=article, value=raw_value)
                else:
                    raw_value = _clean_whitespace(match.group(1))
                    if not raw_value:
                        continue
                    candidate = template.format(value=raw_value)

                if len(candidate) > 140:
                    continue

                saved = self.add_fact(candidate, category=category)
                stored_by_id[saved["id"]] = saved

        # 2) [fact: <text>] blocks emitted by the LLM (they take precedence if they update the same slot).
        for raw_tag_fact in _LLM_FACT_TAG_RE.findall(assistant_raw_text or ""):
            cleaned = _clean_whitespace(raw_tag_fact)
            if not cleaned:
                continue
            category = _infer_category(cleaned)
            saved = self.add_fact(cleaned, category=category)
            stored_by_id[saved["id"]] = saved

        return list(stored_by_id.values())

    def _search_fts_scores_locked(self, query: str) -> dict[int, float]:
        """Find relevant IDs via FTS5 and return a positive score per `fact_id`."""
        if not self._fts_enabled:
            return {}
        tokens = _tokenize_plain(query)
        if not tokens:
            return {}

        fts_expr = " OR ".join(f'"{tok}"*' for tok in tokens[:8])
        try:
            rows = self._conn.execute(
                """
                SELECT rowid AS fact_id, bm25(user_facts_fts) AS rank_score
                FROM user_facts_fts
                WHERE user_facts_fts MATCH ?
                ORDER BY rank_score ASC
                LIMIT 25
                """,
                (fts_expr,),
            ).fetchall()
        except sqlite3.OperationalError:
            return {}

        scores: dict[int, float] = {}
        for idx, row in enumerate(rows):
            scores[int(row["fact_id"])] = max(1.0, 25.0 - idx * 1.5)
        return scores

    def build_memory_context(self, max_chars: int = 1200, query: str = "") -> str:
        """Build a lean context prioritizing `pinned`, relevance (`query`), importance and recency."""
        if max_chars <= 0:
            return ""

        now_dt = _now_utc()
        query_tokens = set(_tokenize_plain(query))

        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, category, fact, updated_at, pinned, importance,
                       access_count, last_accessed, superseded_by
                FROM user_facts
                WHERE superseded_by IS NULL
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()
            rolling_summary = self.get_rolling_summary()
            fts_scores = self._search_fts_scores_locked(query) if query_tokens else {}

        if not rows and not rolling_summary:
            return ""

        scored_items: list[tuple[float, str, int, sqlite3.Row]] = []
        for row in rows:
            fact_id = int(row["id"])
            fact_text = str(row["fact"])
            is_pinned = int(row["pinned"]) == 1
            importance = int(row["importance"])
            ref_dt = _parse_iso_utc(str(row["last_accessed"] or row["updated_at"]))
            age_days = max(0.0, (now_dt - ref_dt).total_seconds() / 86400.0)
            recency_score = math.exp(-age_days / 14.0) * 10.0

            relevance_score = fts_scores.get(fact_id, 0.0)
            if query_tokens:
                fact_tokens = set(_tokenize_plain(fact_text))
                overlap = len(query_tokens & fact_tokens)
                if overlap > 0:
                    relevance_score += (overlap / len(query_tokens)) * 40.0

            total_score = (
                (1000.0 if is_pinned else 0.0)
                + relevance_score
                + (importance * 2.0)
                + recency_score
            )
            scored_items.append((total_score, str(row["updated_at"]), fact_id, row))

        scored_items.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)

        lines: list[str] = []
        current_len = 0
        touched_ids: list[int] = []

        for _score, _updated, fact_id, row in scored_items:
            bullet = f"- {row['fact']}"
            separator_len = 1 if lines else 0
            projected_len = current_len + separator_len + len(bullet)

            if projected_len <= max_chars:
                lines.append(bullet)
                current_len = projected_len
                if query_tokens and (fact_id in fts_scores or bool(query_tokens & set(_tokenize_plain(str(row["fact"]))))):
                    touched_ids.append(fact_id)
            elif not lines:
                if max_chars >= 6:
                    lines.append(bullet[: max_chars - 3].rstrip() + "...")
                else:
                    lines.append(bullet[:max_chars])
                break
            else:
                break

        if touched_ids:
            now_iso = now_dt.isoformat()
            with self._lock, self._conn:
                self._conn.executemany(
                    """
                    UPDATE user_facts
                    SET access_count = access_count + 1, last_accessed = ?
                    WHERE id = ?
                    """,
                    [(now_iso, fid) for fid in touched_ids],
                )

        if rolling_summary:
            summary_line = f"{speech.RECENT_SUMMARY_PREFIX}{rolling_summary}"
            if not lines:
                if len(summary_line) <= max_chars:
                    return summary_line
                if max_chars >= 6:
                    return summary_line[: max_chars - 3].rstrip() + "..."
                return summary_line[:max_chars]

            separator_len = 1
            remaining = max_chars - current_len - separator_len
            if remaining >= 24:
                if len(summary_line) <= remaining:
                    lines.append(summary_line)
                else:
                    lines.append(summary_line[: remaining - 3].rstrip() + "...")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Temporal anchor & the pet's emotional state machine
    # ------------------------------------------------------------------

    def get_temporal_context(self) -> str:
        """Return the part of the day (pt-BR) and the time elapsed since the last interaction."""
        local_now = datetime.now()
        period = speech.day_period(local_now.hour)

        with self._lock:
            row = self._conn.execute(
                "SELECT last_interaction_at FROM companion_state WHERE id = 1"
            ).fetchone()

        last_dt = _parse_iso_utc(str(row["last_interaction_at"])) if row is not None else _now_utc()
        elapsed_secs = max(0.0, (_now_utc() - last_dt).total_seconds())
        elapsed_str = speech.format_elapsed(elapsed_secs)
        return speech.temporal_context_line(period, local_now.strftime("%H:%M"), elapsed_str)

    def _apply_companion_decay(self, row: sqlite3.Row, now_dt: datetime) -> dict[str, Any]:
        """Compute the updated emotional state, applying smooth decay for idle time."""
        last_iso = str(row["last_interaction_at"])
        last_dt = _parse_iso_utc(last_iso)
        dt_hours = max(0.0, (now_dt - last_dt).total_seconds() / 3600.0)

        pleasure_raw = float(row["pleasure"])
        arousal_raw = float(row["arousal"])
        energy_raw = float(row["energy"])
        affinity_raw = float(row["affinity"])

        # Smooth decay toward the emotional baseline.
        baseline_pleasure = 0.15
        pleasure = baseline_pleasure + (pleasure_raw - baseline_pleasure) * math.exp(-dt_hours / 12.0)
        arousal = arousal_raw * math.exp(-dt_hours / 2.0)
        energy = _clamp(energy_raw - (dt_hours * 1.5), 15.0, 100.0)
        affinity_loss = max(0.0, dt_hours - 24.0) * 0.05
        affinity = _clamp(affinity_raw - affinity_loss, 0.0, 100.0)

        pleasure = _clamp(pleasure, -1.0, 1.0)
        arousal = _clamp(arousal, -1.0, 1.0)
        mood = _derive_mood_label(pleasure, arousal, energy)

        return {
            "pleasure": round(pleasure, 4),
            "arousal": round(arousal, 4),
            "energy": round(energy, 2),
            "affinity": round(affinity, 2),
            "mood": mood,
            "last_interaction_at": last_iso,
        }

    def get_companion_state(self) -> dict[str, Any]:
        """Return the pet's current emotional state with time decay applied."""
        now_dt = _now_utc()
        with self._lock:
            row = self._conn.execute(
                """
                SELECT pleasure, arousal, energy, affinity, last_interaction_at
                FROM companion_state
                WHERE id = 1
                """
            ).fetchone()
        assert row is not None
        return self._apply_companion_decay(row, now_dt)

    def record_interaction(self, sentiment_delta: float = 0.08) -> dict[str, Any]:
        """Record a conversation and update the pet's mood, energy and affinity."""
        now_dt = _now_utc()
        now_iso = now_dt.isoformat()
        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT pleasure, arousal, energy, affinity, last_interaction_at
                FROM companion_state
                WHERE id = 1
                """
            ).fetchone()
            assert row is not None
            current = self._apply_companion_decay(row, now_dt)

            new_pleasure = _clamp(current["pleasure"] + float(sentiment_delta), -1.0, 1.0)
            new_arousal = _clamp(
                current["arousal"] + abs(float(sentiment_delta)) * 0.5 + 0.04,
                -1.0,
                1.0,
            )
            new_energy = _clamp(current["energy"] + 1.5, 0.0, 100.0)
            affinity_gain = 0.6 if sentiment_delta >= 0 else 0.1
            new_affinity = _clamp(current["affinity"] + affinity_gain, 0.0, 100.0)

            self._conn.execute(
                """
                UPDATE companion_state
                SET pleasure = ?, arousal = ?, energy = ?, affinity = ?, last_interaction_at = ?
                WHERE id = 1
                """,
                (new_pleasure, new_arousal, new_energy, new_affinity, now_iso),
            )

        return {
            "pleasure": round(new_pleasure, 4),
            "arousal": round(new_arousal, 4),
            "energy": round(new_energy, 2),
            "affinity": round(new_affinity, 2),
            "mood": _derive_mood_label(new_pleasure, new_arousal, new_energy),
            "last_interaction_at": now_iso,
        }

    def record_pet(self, intensity: float = 1.0) -> dict[str, Any]:
        """Record a pat on the pet's face, raising affinity, energy and pleasure."""
        clamped_intensity = _clamp(float(intensity), 0.1, 3.0)
        now_dt = _now_utc()
        now_iso = now_dt.isoformat()

        with self._lock, self._conn:
            row = self._conn.execute(
                """
                SELECT pleasure, arousal, energy, affinity, last_interaction_at
                FROM companion_state
                WHERE id = 1
                """
            ).fetchone()
            assert row is not None
            current = self._apply_companion_decay(row, now_dt)

            new_pleasure = _clamp(current["pleasure"] + 0.14 * clamped_intensity, -1.0, 1.0)
            new_arousal = _clamp(current["arousal"] + 0.06 * clamped_intensity, -1.0, 1.0)
            new_energy = _clamp(current["energy"] + 3.0 * clamped_intensity, 0.0, 100.0)
            new_affinity = _clamp(current["affinity"] + 1.8 * clamped_intensity, 0.0, 100.0)

            self._conn.execute(
                """
                UPDATE companion_state
                SET pleasure = ?, arousal = ?, energy = ?, affinity = ?, last_interaction_at = ?
                WHERE id = 1
                """,
                (new_pleasure, new_arousal, new_energy, new_affinity, now_iso),
            )

        return {
            "pleasure": round(new_pleasure, 4),
            "arousal": round(new_arousal, 4),
            "energy": round(new_energy, 2),
            "affinity": round(new_affinity, 2),
            "mood": _derive_mood_label(new_pleasure, new_arousal, new_energy),
            "last_interaction_at": now_iso,
        }

    def get_companion_prompt_line(self) -> str:
        """Return a compact emotional-tone line for the prompt (without altering factual accuracy)."""
        state = self.get_companion_state()
        return speech.companion_prompt_line(state["mood"], state["energy"], state["affinity"])

    def clear_short_term(self) -> None:
        """Delete only the recent history and rolling summary, keeping learned facts."""
        now_iso = _now_iso()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM messages")
            self._conn.execute(
                "UPDATE rolling_state SET summary = '', updated_at = ? WHERE id = 1",
                (now_iso,),
            )

    def clear_all(self) -> None:
        """Delete the short-term history, rolling summary and all long-term facts."""
        now_iso = _now_iso()
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM messages")
            self._conn.execute("DELETE FROM user_facts")
            if self._fts_enabled:
                self._conn.execute("DELETE FROM user_facts_fts")
            self._conn.execute(
                "UPDATE rolling_state SET summary = '', updated_at = ? WHERE id = 1",
                (now_iso,),
            )

    def get_meta(self, key: str) -> str | None:
        """Read a value persisted in the `app_meta` table."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM app_meta WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row is not None else None

    def set_meta(self, key: str, value: str) -> None:
        """Write or update a value in the `app_meta` table."""
        now_iso = _now_iso()
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO app_meta (key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now_iso),
            )
