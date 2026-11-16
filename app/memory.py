"""Sistema de memória persistente em duas camadas (curto e longo prazo) com SQLite."""

from __future__ import annotations

import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import BASE_DIR

_DEFAULT_DB_PATH = BASE_DIR / "data" / "memory.db"

# Padrões de fatos emitidos explicitamente pelo LLM no texto bruto
_LLM_FACT_TAG_RE = re.compile(r"\[fact\s*:\s*([^\]]+)\]", re.IGNORECASE)

# Padrões para identificar fatos de atributo único (atualizam em vez de duplicar)
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

# Padrões heurísticos em PT-BR e EN para capturar fatos explícitos da fala do usuário
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


def _now_iso() -> str:
    """Retorna o timestamp UTC atual no formato ISO-8601."""
    return datetime.now(timezone.utc).isoformat()


def _strip_accents(text: str) -> str:
    """Remove acentos mantendo apenas caracteres base para normalização de chaves."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _clean_whitespace(text: str) -> str:
    """Colapsa espaços repetidos e remove espaços nas pontas."""
    return " ".join(text.strip().split())


def _normalize_fact_key(fact: str, category: str = "general") -> str:
    """Gera chave normalizada para deduplicar e atualizar fatos semelhantes."""
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


def _infer_category(fact_text: str) -> str:
    """Infere categoria simples para fatos extraídos por tag sem categoria explícita."""
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
    """Divide o texto do usuário em sentenças curtas para extração segura."""
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


class MemoryStore:
    """Armazenamento em duas camadas (mensagens recentes e fatos do usuário) via SQLite."""

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

        if not self._is_in_memory:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._initialize_db()

    def _initialize_db(self) -> None:
        """Habilita WAL/integridade e cria tabelas necessárias caso não existam."""
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
                        updated_at TEXT NOT NULL
                    )
                    """
                )

    def close(self) -> None:
        """Fecha a conexão SQLite de forma segura."""
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------------
    # Camada 1: Curto Prazo (Janela Deslizante de Mensagens)
    # ------------------------------------------------------------------

    def add_message(
        self,
        role: str,
        content: str,
        emotion: str | None = None,
    ) -> int:
        """Registra uma mensagem na memória de curto prazo e retorna seu ID."""
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
        """Retorna as últimas mensagens em ordem cronológica sem inflar o contexto."""
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
        """Retorna a quantidade de mensagens armazenadas atualmente na camada 1."""
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS total FROM messages").fetchone()
        return int(row["total"]) if row is not None else 0

    # ------------------------------------------------------------------
    # Camada 2: Longo Prazo (Perfil e Fatos Aprendidos)
    # ------------------------------------------------------------------

    def add_fact(self, fact: str, category: str = "general") -> dict[str, Any]:
        """Adiciona ou atualiza um fato deduplicado e aplica o limite `max_user_facts`."""
        cleaned_fact = _clean_whitespace(fact)
        if not cleaned_fact:
            raise ValueError("O fato não pode ser vazio.")

        cleaned_category = _clean_whitespace(category).lower() or "general"
        normalized_key = _normalize_fact_key(cleaned_fact, cleaned_category)
        updated_at = _now_iso()

        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO user_facts (category, fact, normalized_key, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(normalized_key) DO UPDATE SET
                    category = excluded.category,
                    fact = excluded.fact,
                    updated_at = excluded.updated_at
                """,
                (cleaned_category, cleaned_fact, normalized_key, updated_at),
            )

            # Remove fatos mais antigos caso exceda o orçamento máximo configurado.
            overflow_rows = self._conn.execute(
                """
                SELECT id
                FROM user_facts
                ORDER BY updated_at DESC, id DESC
                LIMIT -1 OFFSET ?
                """,
                (self.max_user_facts,),
            ).fetchall()
            if overflow_rows:
                ids_to_delete = [(int(row["id"]),) for row in overflow_rows]
                self._conn.executemany(
                    "DELETE FROM user_facts WHERE id = ?",
                    ids_to_delete,
                )

            saved = self._conn.execute(
                """
                SELECT id, category, fact, updated_at
                FROM user_facts
                WHERE normalized_key = ?
                """,
                (normalized_key,),
            ).fetchone()

        assert saved is not None
        return {
            "id": int(saved["id"]),
            "category": str(saved["category"]),
            "fact": str(saved["fact"]),
            "updated_at": str(saved["updated_at"]),
        }

    def get_facts(self) -> list[dict[str, Any]]:
        """Lista todos os fatos aprendidos do mais recente para o mais antigo."""
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT id, category, fact, updated_at
                FROM user_facts
                ORDER BY updated_at DESC, id DESC
                """
            ).fetchall()

        return [
            {
                "id": int(row["id"]),
                "category": str(row["category"]),
                "fact": str(row["fact"]),
                "updated_at": str(row["updated_at"]),
            }
            for row in rows
        ]

    def delete_fact(self, fact_id: int) -> bool:
        """Remove um fato pelo ID e informa se algum registro foi excluído."""
        with self._lock, self._conn:
            cursor = self._conn.execute(
                "DELETE FROM user_facts WHERE id = ?",
                (int(fact_id),),
            )
            return cursor.rowcount > 0

    def extract_and_store_facts(
        self,
        user_text: str,
        assistant_raw_text: str,
    ) -> list[dict[str, Any]]:
        """Extrai fatos de tags `[fact: ...]` do LLM e heurísticas explícitas do usuário."""
        stored_by_id: dict[int, dict[str, Any]] = {}

        # 1) Fatos heurísticos explícitos presentes na mensagem do usuário (PT-BR / EN).
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

        # 2) Blocos [fact: <texto>] emitidos pelo LLM (têm precedência se atualizarem o mesmo slot).
        for raw_tag_fact in _LLM_FACT_TAG_RE.findall(assistant_raw_text or ""):
            cleaned = _clean_whitespace(raw_tag_fact)
            if not cleaned:
                continue
            category = _infer_category(cleaned)
            saved = self.add_fact(cleaned, category=category)
            stored_by_id[saved["id"]] = saved

        return list(stored_by_id.values())

    def build_memory_context(self, max_chars: int = 1200) -> str:
        """Monta bloco compacto em bullet points respeitando o limite rígido de `max_chars`."""
        if max_chars <= 0:
            return ""

        facts = self.get_facts()
        if not facts:
            return ""

        lines: list[str] = []
        current_len = 0

        for item in facts:
            bullet = f"- {item['fact']}"
            separator_len = 1 if lines else 0
            projected_len = current_len + separator_len + len(bullet)

            if projected_len <= max_chars:
                lines.append(bullet)
                current_len = projected_len
            elif not lines:
                # Se nem o primeiro item couber inteiro, trunca com segurança dentro do orçamento.
                if max_chars >= 6:
                    lines.append(bullet[: max_chars - 3].rstrip() + "...")
                else:
                    lines.append(bullet[:max_chars])
                break
            else:
                break

        return "\n".join(lines)

    def clear_short_term(self) -> None:
        """Apaga apenas o histórico recente (`messages`), preservando fatos aprendidos."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM messages")

    def clear_all(self) -> None:
        """Apaga tanto o histórico de curto prazo quanto todos os fatos de longo prazo."""
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM messages")
            self._conn.execute("DELETE FROM user_facts")
