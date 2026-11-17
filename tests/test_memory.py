"""Unit tests for configuration, secret redaction and two-layer memory."""

from __future__ import annotations

import logging
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import BASE_DIR, Settings, configure_logging, load_settings
from app.memory import MemoryStore


def test_load_settings_defaults_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Check the `Settings` defaults and loading via `.env`/environment."""
    for key in (
        "LLM_BASE_URL",
        "LLM_API_KEY",
        "LLM_MODEL",
        "HOST",
        "PORT",
        "MAX_SHORT_TERM_MESSAGES",
        "MAX_USER_FACTS",
        "DB_PATH",
    ):
        monkeypatch.delenv(key, raising=False)

    defaults = load_settings(env_path=tmp_path / "nonexistent.env")
    assert isinstance(defaults, Settings)
    assert defaults.llm_base_url == "http://127.0.0.1:31415/v1"
    assert defaults.llm_api_key == ""
    assert defaults.llm_model == "claude-haiku-4-5"
    assert defaults.host == "0.0.0.0"
    assert defaults.port == 8000
    assert defaults.max_short_term_messages == 10
    assert defaults.max_user_facts == 25
    assert defaults.db_path == BASE_DIR / "data" / "memory.db"

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "LLM_BASE_URL=http://localhost:9999/v1/",
                "LLM_API_KEY=freellmapi-teste-123456",
                "LLM_MODEL=modelo-local",
                "HOST=127.0.0.1",
                "PORT=8123",
                "MAX_SHORT_TERM_MESSAGES=12",
                "MAX_USER_FACTS=30",
                "DB_PATH=custom/mem.db",
            ]
        ),
        encoding="utf-8",
    )

    loaded = load_settings(env_path=env_file)
    assert loaded.llm_base_url == "http://localhost:9999/v1"
    assert loaded.llm_api_key == "freellmapi-teste-123456"
    assert loaded.llm_model == "modelo-local"
    assert loaded.host == "127.0.0.1"
    assert loaded.port == 8123
    assert loaded.max_short_term_messages == 12
    assert loaded.max_user_facts == 30
    assert loaded.db_path == (BASE_DIR / "custom" / "mem.db").resolve()


def test_logging_redacts_api_key_and_known_secret_patterns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Ensure `LLM_API_KEY` and `freellmapi-*`/`sk-*` tokens never leak into the logs."""
    custom_secret = "custom-secret-xyz-987"
    configure_logging(secret=custom_secret, level=logging.INFO)
    logger = logging.getLogger("desk_assistant.test_logger")

    with caplog.at_level(logging.INFO):
        logger.info("Failure with key=%s", custom_secret)
        logger.warning("Token detected: freellmapi-abc123_XYZ and sk-proj_999888")
        logger.error("Header Authorization: Bearer meu_token_secreto_42 model=claude-haiku-4-5")

    joined = caplog.text
    assert custom_secret not in joined
    assert "freellmapi-abc123_XYZ" not in joined
    assert "sk-proj_999888" not in joined
    assert "meu_token_secreto_42" not in joined
    assert "[REDACTED]" in joined
    assert "model=claude-haiku-4-5" in joined


def test_short_term_sliding_window_returns_last_messages_in_order(tmp_path: Path) -> None:
    """Confirm automatic directory creation and the chronological sliding window."""
    db_file = tmp_path / "nested" / "sub" / "memory.db"
    store = MemoryStore(db_path=db_file, max_short_term_messages=10)
    try:
        assert db_file.exists()
        for idx in range(15):
            role = "user" if idx % 2 == 0 else "assistant"
            store.add_message(role, f"message-{idx}", emotion="neutral" if role == "assistant" else None)

        assert store.get_recent_messages_count() == 15

        recent = store.get_recent_messages()
        assert len(recent) == 10
        assert [m["content"] for m in recent] == [f"message-{i}" for i in range(5, 15)]
        assert all(set(m.keys()) == {"role", "content"} for m in recent)

        last_three = store.get_recent_messages(limit=3)
        assert [m["content"] for m in last_three] == ["message-12", "message-13", "message-14"]
    finally:
        store.close()


def test_extract_and_store_facts_from_tags_and_ptbr_heuristics(tmp_path: Path) -> None:
    """Extract the LLM `[fact: ...]` tags and pt-BR heuristic facts without inventing data."""
    store = MemoryStore(db_path=tmp_path / "memory.db")
    try:
        stored = store.extract_and_store_facts(
            user_text="Oi! Meu nome é Nathan, e eu prefiro respostas curtas. Trabalho com Python e moro em São Paulo.",
            assistant_raw_text=(
                "[emotion:happy] Prazer, Nathan! Vou responder de forma direta. "
                "[fact: Gosta de café preto] [fact:Usa macOS no dia a dia]"
            ),
        )

        fact_texts = [item["fact"] for item in store.get_facts()]
        assert len(stored) >= 5
        assert "Nome do usuário: Nathan" in fact_texts
        assert "Prefere respostas curtas" in fact_texts
        assert "Trabalha com Python" in fact_texts
        assert "Mora em São Paulo" in fact_texts
        assert "Gosta de café preto" in fact_texts
        assert "Usa macOS no dia a dia" in fact_texts

        # Questions and vague sentences must not produce spurious facts.
        store.extract_and_store_facts(
            user_text="Você gosta de café? Tenho uma dúvida sobre Python.",
            assistant_raw_text="[emotion:curious] Claro, qual é a dúvida?",
        )
        updated_texts = [item["fact"] for item in store.get_facts()]
        assert updated_texts == fact_texts
    finally:
        store.close()


def test_fact_deduplication_and_max_user_facts_eviction(tmp_path: Path) -> None:
    """Ensure updating instead of duplicating, and removal of the oldest above the limit."""
    store = MemoryStore(db_path=tmp_path / "memory.db", max_user_facts=4)
    try:
        first_name = store.add_fact("Nome do usuário: Nathan", category="identity")
        second_name = store.add_fact("Nome: Lucas", category="identity")
        assert first_name["id"] == second_name["id"]
        assert len(store.get_facts()) == 1
        assert store.get_facts()[0]["fact"] == "Nome: Lucas"

        store.add_fact("Idioma: português", category="preference")
        store.add_fact("Idioma: inglês", category="preference")
        assert len(store.get_facts()) == 2

        # Add more facts to exceed max_user_facts=4 and verify the oldest are removed.
        store.add_fact("Gosta de café")
        store.add_fact("Prefere tema escuro")
        store.add_fact("Usa atalhos de teclado")

        facts = store.get_facts()
        assert len(facts) == 4
        texts = [f["fact"] for f in facts]
        assert "Nome: Lucas" not in texts
        assert "Usa atalhos de teclado" in texts

        target_id = facts[0]["id"]
        assert store.delete_fact(target_id) is True
        assert store.delete_fact(target_id) is False
    finally:
        store.close()


def test_build_memory_context_respects_hard_char_budget(tmp_path: Path) -> None:
    """Ensure an empty result without facts and a hard `max_chars` budget."""
    store = MemoryStore(db_path=tmp_path / "memory.db")
    try:
        assert store.build_memory_context() == ""

        for i in range(6):
            store.add_fact(f"Preferência número {i}: manter respostas objetivas e claras")

        full_ctx = store.build_memory_context(max_chars=1200)
        assert full_ctx.startswith("- ")
        assert len(full_ctx) <= 1200

        tight_ctx = store.build_memory_context(max_chars=90)
        assert 0 < len(tight_ctx) <= 90
        assert tight_ctx.startswith("- ")

        tiny_ctx = store.build_memory_context(max_chars=20)
        assert 0 < len(tiny_ctx) <= 20
    finally:
        store.close()


def test_clear_short_term_preserves_facts_and_clear_all_wipes_both(tmp_path: Path) -> None:
    """Check that `clear_short_term` keeps facts and `clear_all` clears both layers."""
    store = MemoryStore(db_path=tmp_path / "memory.db")
    try:
        store.add_message("user", "Olá")
        store.add_message("assistant", "Oi!", emotion="happy")
        store.add_fact("Nome do usuário: Nathan", category="identity")

        store.clear_short_term()
        assert store.get_recent_messages_count() == 0
        assert store.get_recent_messages() == []
        assert len(store.get_facts()) == 1

        store.clear_all()
        assert store.get_recent_messages_count() == 0
        assert store.get_facts() == []
    finally:
        store.close()


def test_load_settings_extended_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Validate the defaults and overrides of the new optional `Settings` fields."""
    for key in (
        "HTTPS_PORT",
        "CERT_FILE",
        "KEY_FILE",
        "STT_MODEL",
        "STT_LANGUAGE",
        "TTS_VOICE",
        "WEATHER_LATITUDE",
        "WEATHER_LONGITUDE",
        "WEATHER_CITY",
    ):
        monkeypatch.delenv(key, raising=False)

    defaults = load_settings(env_path=tmp_path / "nonexistent.env")
    assert defaults.https_port == 8443
    assert defaults.cert_file == BASE_DIR / "certs" / "cert.pem"
    assert defaults.key_file == BASE_DIR / "certs" / "key.pem"
    assert defaults.stt_model == "base"
    assert defaults.stt_language == "pt"
    assert defaults.tts_voice == "Luciana"
    assert defaults.weather_latitude == pytest.approx(-23.5505)
    assert defaults.weather_longitude == pytest.approx(-46.6333)
    assert defaults.weather_city == "São Paulo"

    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "HTTPS_PORT=9443",
                "CERT_FILE=custom_certs/c.pem",
                "KEY_FILE=custom_certs/k.pem",
                "STT_MODEL=small",
                "STT_LANGUAGE=en",
                "TTS_VOICE=Eddy",
                "WEATHER_LATITUDE=-22.9068",
                "WEATHER_LONGITUDE=-43.1729",
                "WEATHER_CITY=Rio de Janeiro",
            ]
        ),
        encoding="utf-8",
    )
    loaded = load_settings(env_path=env_file)
    assert loaded.https_port == 9443
    assert loaded.cert_file == (BASE_DIR / "custom_certs" / "c.pem").resolve()
    assert loaded.key_file == (BASE_DIR / "custom_certs" / "k.pem").resolve()
    assert loaded.stt_model == "small"
    assert loaded.stt_language == "en"
    assert loaded.tts_voice == "Eddy"
    assert loaded.weather_latitude == pytest.approx(-22.9068)
    assert loaded.weather_longitude == pytest.approx(-43.1729)
    assert loaded.weather_city == "Rio de Janeiro"


def test_idempotent_sqlite_migration_from_phase1_schema(tmp_path: Path) -> None:
    """Ensure a safe, idempotent migration of a legacy Phase 1 SQLite database."""
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(db_file))
    with conn:
        conn.execute(
            """
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                emotion TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE user_facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                fact TEXT NOT NULL,
                normalized_key TEXT NOT NULL UNIQUE,
                updated_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO user_facts (category, fact, normalized_key, updated_at)
            VALUES ('identity', 'Nome do usuário: Nathan', 'attr:name', '2026-01-01T10:00:00+00:00')
            """
        )
    conn.close()

    # First open migrates columns, new tables and FTS5.
    store = MemoryStore(db_path=db_file)
    try:
        facts = store.get_facts()
        assert len(facts) == 1
        assert facts[0]["fact"] == "Nome do usuário: Nathan"
        assert facts[0]["pinned"] is False
        assert facts[0]["importance"] == 5
        assert facts[0]["access_count"] == 1
        assert facts[0]["last_accessed"] == "2026-01-01T10:00:00+00:00"
        assert facts[0]["superseded_by"] is None
        assert store.get_rolling_summary() == ""
        state = store.get_companion_state()
        assert state["energy"] > 0
    finally:
        store.close()

    # The second open must be 100% idempotent.
    store_again = MemoryStore(db_path=db_file)
    try:
        assert len(store_again.get_facts()) == 1
        ctx = store_again.build_memory_context(query="Nathan")
        assert "Nathan" in ctx
    finally:
        store_again.close()


def test_pinned_facts_protected_from_eviction_and_importance_update(tmp_path: Path) -> None:
    """Facts marked `pinned=True` are never removed when `max_user_facts` is exceeded."""
    store = MemoryStore(db_path=tmp_path / "pinned.db", max_user_facts=3)
    try:
        core = store.add_fact("Nome do usuário: Nathan", category="identity", pinned=True, importance=10)
        assert core["pinned"] is True
        assert core["importance"] == 10

        f2 = store.add_fact("Gosta de café")
        updated_f2 = store.update_fact_importance(f2["id"], 9)
        assert updated_f2 is not None
        assert updated_f2["importance"] == 9
        assert store.update_fact_importance(99999, 5) is None
        assert store.set_fact_pinned(99999, True) is None

        store.add_fact("Usa macOS")
        store.add_fact("Prefere tema escuro")
        store.add_fact("Usa atalho Cmd+Opt+F")

        facts = store.get_facts()
        texts = [f["fact"] for f in facts]
        assert "Nome do usuário: Nathan" in texts
        assert len(facts) == 3

        # Also tests `set_fact_pinned` after creation.
        dark_fact = next(f for f in facts if f["fact"] == "Prefere tema escuro")
        pinned_dark = store.set_fact_pinned(dark_fact["id"], True)
        assert pinned_dark is not None and pinned_dark["pinned"] is True
        store.add_fact("Escuta synthwave")
        texts_after = [f["fact"] for f in store.get_facts()]
        assert "Nome do usuário: Nathan" in texts_after
        assert "Prefere tema escuro" in texts_after
    finally:
        store.close()


def test_rolling_summary_query_ranking_and_budget(tmp_path: Path) -> None:
    """Validate `rolling_state`, relevance/`pinned` ranking and respect for `max_chars`."""
    store = MemoryStore(db_path=tmp_path / "context.db")
    try:
        assert store.get_rolling_summary() == ""
        saved_summary = store.update_rolling_summary("Nathan configurou atalhos no macOS.")
        assert saved_summary == "Nathan configurou atalhos no macOS."
        assert store.get_rolling_summary() == "Nathan configurou atalhos no macOS."

        store.add_fact("Mora em São Paulo", category="location", pinned=True, importance=8)
        store.add_fact("Prefere café preto sem açúcar", category="preference", importance=4)
        store.add_fact("Usa editor Neovim para Python", category="work", importance=7)

        ctx = store.build_memory_context(max_chars=120, query="Python Neovim")
        assert len(ctx) <= 120
        assert "São Paulo" in ctx
        assert "Neovim" in ctx

        full_ctx = store.build_memory_context(max_chars=1200, query="Python")
        assert "Resumo recente:" in full_ctx
        assert len(full_ctx) <= 1200
    finally:
        store.close()


def test_companion_state_interactions_pet_and_decay(tmp_path: Path) -> None:
    """Validate emotional evolution (`record_interaction`, `record_pet`), decay and the prompt line."""
    store = MemoryStore(db_path=tmp_path / "companion.db")
    try:
        initial = store.get_companion_state()
        assert 0.0 <= initial["energy"] <= 100.0
        assert 0.0 <= initial["affinity"] <= 100.0
        assert -1.0 <= initial["pleasure"] <= 1.0

        after_chat = store.record_interaction(sentiment_delta=0.12)
        assert after_chat["affinity"] > initial["affinity"]
        assert after_chat["pleasure"] >= initial["pleasure"]

        after_pet = store.record_pet(intensity=1.5)
        assert after_pet["affinity"] > after_chat["affinity"]
        assert after_pet["energy"] >= after_chat["energy"]

        prompt_line = store.get_companion_prompt_line()
        assert "Estado do pet:" in prompt_line
        assert "energia" in prompt_line
        assert "afinidade" in prompt_line

        # Simulate 10 hours without interaction directly in SQLite to check the decay.
        ten_hours_ago = (datetime.now(timezone.utc) - timedelta(hours=10)).isoformat()
        with store._conn:
            store._conn.execute(
                "UPDATE companion_state SET last_interaction_at = ? WHERE id = 1",
                (ten_hours_ago,),
            )
        decayed = store.get_companion_state()
        assert decayed["energy"] < after_pet["energy"]
        assert decayed["arousal"] < after_pet["arousal"]
    finally:
        store.close()


def test_temporal_context_and_consolidate_facts(tmp_path: Path) -> None:
    """Validate the pt-BR temporal context and consolidation of duplicate/contradictory facts."""
    store = MemoryStore(db_path=tmp_path / "consolidate.db")
    try:
        temporal = store.get_temporal_context()
        assert any(p in temporal for p in ("manhã", "tarde", "noite", "madrugada"))
        assert "Última interação:" in temporal

        old_fact = store.add_fact("Gosta de café", category="preference", pinned=True)
        new_fact = store.add_fact("Não gosta de café", category="preference")
        old_work = store.add_fact("Trabalha como dev júnior", category="work")
        new_work = store.add_fact("Trabalha como engenheiro sênior", category="work")

        consolidated = store.consolidate_facts()
        assert consolidated == 2

        active = store.get_facts()
        active_ids = {f["id"] for f in active}
        assert new_fact["id"] in active_ids
        assert new_work["id"] in active_ids
        assert old_fact["id"] not in active_ids
        assert old_work["id"] not in active_ids

        # Verify `pinned=True` is transferred to the winner and `superseded_by` is set.
        all_rows = store.get_facts(include_superseded=True)
        by_id = {f["id"]: f for f in all_rows}
        assert by_id[old_fact["id"]]["superseded_by"] == new_fact["id"]
        assert by_id[old_work["id"]]["superseded_by"] == new_work["id"]
        assert by_id[new_fact["id"]]["pinned"] is True
    finally:
        store.close()
