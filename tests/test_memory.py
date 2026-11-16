"""Testes unitários para configuração, redação de segredos e memória em 2 camadas."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import BASE_DIR, Settings, configure_logging, load_settings
from app.memory import MemoryStore


def test_load_settings_defaults_and_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verifica valores padrão do `Settings` e carregamento via `.env`/ambiente."""
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

    defaults = load_settings(env_path=tmp_path / "inexistente.env")
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
    """Garante que `LLM_API_KEY` e tokens `freellmapi-*`/`sk-*` nunca vazam nos logs."""
    custom_secret = "segredo-customizado-xyz-987"
    configure_logging(secret=custom_secret, level=logging.INFO)
    logger = logging.getLogger("desk_assistant.test_logger")

    with caplog.at_level(logging.INFO):
        logger.info("Falha com chave=%s", custom_secret)
        logger.warning("Token detectado: freellmapi-abc123_XYZ e sk-proj_999888")
        logger.error("Header Authorization: Bearer meu_token_secreto_42 model=claude-haiku-4-5")

    joined = caplog.text
    assert custom_secret not in joined
    assert "freellmapi-abc123_XYZ" not in joined
    assert "sk-proj_999888" not in joined
    assert "meu_token_secreto_42" not in joined
    assert "[REDACTED]" in joined
    assert "model=claude-haiku-4-5" in joined


def test_short_term_sliding_window_returns_last_messages_in_order(tmp_path: Path) -> None:
    """Confirma criação automática de diretórios e janela deslizante cronológica."""
    db_file = tmp_path / "nested" / "sub" / "memory.db"
    store = MemoryStore(db_path=db_file, max_short_term_messages=10)
    try:
        assert db_file.exists()
        for idx in range(15):
            role = "user" if idx % 2 == 0 else "assistant"
            store.add_message(role, f"mensagem-{idx}", emotion="neutral" if role == "assistant" else None)

        assert store.get_recent_messages_count() == 15

        recent = store.get_recent_messages()
        assert len(recent) == 10
        assert [m["content"] for m in recent] == [f"mensagem-{i}" for i in range(5, 15)]
        assert all(set(m.keys()) == {"role", "content"} for m in recent)

        last_three = store.get_recent_messages(limit=3)
        assert [m["content"] for m in last_three] == ["mensagem-12", "mensagem-13", "mensagem-14"]
    finally:
        store.close()


def test_extract_and_store_facts_from_tags_and_ptbr_heuristics(tmp_path: Path) -> None:
    """Extrai tags `[fact: ...]` do LLM e fatos heurísticos em PT-BR sem inventar dados."""
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

        # Perguntas e frases vagas não devem gerar fatos espúrios.
        store.extract_and_store_facts(
            user_text="Você gosta de café? Tenho uma dúvida sobre Python.",
            assistant_raw_text="[emotion:curious] Claro, qual é a dúvida?",
        )
        updated_texts = [item["fact"] for item in store.get_facts()]
        assert updated_texts == fact_texts
    finally:
        store.close()


def test_fact_deduplication_and_max_user_facts_eviction(tmp_path: Path) -> None:
    """Garante atualização em vez de duplicação e remoção dos mais antigos acima do limite."""
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

        # Adiciona mais fatos para exceder max_user_facts=4 e verificar remoção dos mais antigos.
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
    """Garante retorno vazio sem fatos e orçamento rígido de `max_chars`."""
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
    """Verifica que `clear_short_term` mantém fatos e `clear_all` limpa ambas as camadas."""
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
