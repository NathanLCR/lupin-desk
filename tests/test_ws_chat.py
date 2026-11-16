"""Testes de API HTTP, WebSocket e streaming LLM para o assistente de mesa."""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.llm import LLMClient, TagStreamParser, build_system_prompt
from app.main import create_app
from app.memory import MemoryStore


def _build_sse_stream(chunks: list[dict]) -> bytes:
    """Serializa uma lista de payloads delta OpenAI-compatible no formato SSE."""
    lines = [f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n" for chunk in chunks]
    lines.append("data: [DONE]\n\n")
    return "".join(lines).encode("utf-8")


def _make_settings(tmp_path: Path, api_key: str = "freellmapi-segredo-teste-123") -> Settings:
    """Cria Settings isolado apontando para banco SQLite temporário."""
    return Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key=api_key,
        llm_model="claude-haiku-4-5",
        host="127.0.0.1",
        port=8000,
        max_short_term_messages=10,
        max_user_facts=25,
        db_path=tmp_path / "test_memory.db",
    )


def test_tag_stream_parser_quebra_tags_e_fallback_emocao() -> None:
    """Garante que tags quebradas entre chunks não vazam e emoção inválida vira neutral."""
    parser = TagStreamParser()
    chunks = ["[emo", "tion:hap", "py] Olá! [fact: Gosta", " de café]"]
    eventos = []
    for chunk in chunks:
        eventos.extend(parser.feed(chunk))
    finais, clean_text, raw_text, emotion = parser.finish()
    eventos.extend(finais)

    assert emotion == "happy"
    assert clean_text == "Olá!"
    assert "[fact: Gosta de café]" in raw_text
    assert eventos[0] == {"type": "emotion", "emotion": "happy"}
    deltas = "".join(ev["text"] for ev in eventos if ev["type"] == "delta")
    assert "[" not in deltas
    assert "fact" not in deltas
    assert "emotion" not in deltas
    assert deltas.strip() == "Olá!"

    # Testa fallback para neutral quando emoção não é suportada.
    parser_invalido = TagStreamParser()
    ev_inv = parser_invalido.feed("[emotion:alienigena] Tudo bem?")
    f_inv, clean_inv, _, emo_inv = parser_invalido.finish()
    ev_inv.extend(f_inv)
    assert emo_inv == "neutral"
    assert clean_inv == "Tudo bem?"
    assert ev_inv[0] == {"type": "emotion", "emotion": "neutral"}

    # Testa resposta sem tag de emoção inicial.
    parser_sem_tag = TagStreamParser()
    ev_sem = parser_sem_tag.feed("Sem tag inicial.")
    f_sem, clean_sem, _, emo_sem = parser_sem_tag.finish()
    ev_sem.extend(f_sem)
    assert emo_sem == "neutral"
    assert clean_sem == "Sem tag inicial."
    assert ev_sem[0] == {"type": "emotion", "emotion": "neutral"}


def test_http_endpoints_e_crud_memoria(tmp_path: Path) -> None:
    """Valida /, /health e todos os endpoints HTTP de memória."""
    settings = _make_settings(tmp_path)
    store = MemoryStore(db_path=settings.db_path)
    app = create_app(settings=settings, memory_store=store, llm_client=LLMClient(settings))

    with TestClient(app) as client:
        res_root = client.get("/")
        assert res_root.status_code == 200
        assert "text/html" in res_root.headers["content-type"]

        res_health = client.get("/health")
        assert res_health.status_code == 200
        assert res_health.json() == {"status": "ok", "model": "claude-haiku-4-5"}

        res_mem = client.get("/api/memory")
        assert res_mem.status_code == 200
        assert res_mem.json() == {"facts": [], "recent_messages_count": 0}

        # Fato vazio deve retornar 400.
        res_empty = client.post("/api/memory/facts", json={"fact": "   "})
        assert res_empty.status_code == 400

        # Criação válida retorna 201.
        res_created = client.post(
            "/api/memory/facts",
            json={"fact": "Prefere café sem açúcar", "category": "preference"},
        )
        assert res_created.status_code == 201
        created = res_created.json()
        assert created["fact"] == "Prefere café sem açúcar"
        assert created["category"] == "preference"
        fact_id = created["id"]

        # Deleção e 404 subsequente.
        res_del = client.delete(f"/api/memory/facts/{fact_id}")
        assert res_del.status_code == 200
        assert client.delete(f"/api/memory/facts/{fact_id}").status_code == 404

        # Adiciona mensagem e novo fato para testar /api/memory/clear.
        store.add_message("user", "Oi")
        client.post("/api/memory/facts", json={"fact": "Mora em São Paulo"})

        res_clear_short = client.post("/api/memory/clear")
        assert res_clear_short.status_code == 200
        body_short = res_clear_short.json()
        assert body_short["recent_messages_count"] == 0
        assert len(body_short["facts"]) == 1

        res_clear_all = client.post("/api/memory/clear", json={"include_facts": True})
        assert res_clear_all.status_code == 200
        assert res_clear_all.json() == {"facts": [], "recent_messages_count": 0}

    store.close()


def test_websocket_fluxo_completo_e_quirk_reasoning(tmp_path: Path) -> None:
    """Valida typing, streaming com tag quebrada, reasoning ignorado, fatos e clear_history."""
    captured_requests: list[dict] = []

    sse_payload = _build_sse_stream(
        [
            {"choices": [{"delta": {"reasoning": "Vou pensar em PT-BR antes de responder..."}}]},
            {"choices": [{"delta": {"reasoning": "Mais raciocínio interno secreto."}}]},
            {"choices": [{"delta": {"content": "[emo"}}]},
            {"choices": [{"delta": {"content": "tion:hap"}}]},
            {"choices": [{"delta": {"content": "py] Olá! [fact: Gosta"}}]},
            {"choices": [{"delta": {"content": " de café]"}}]},
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured_requests.append(
            {
                "url": str(request.url),
                "auth": request.headers.get("authorization"),
                "json": json.loads(request.content.decode("utf-8")),
            }
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_payload,
        )

    settings = _make_settings(tmp_path)
    store = MemoryStore(db_path=settings.db_path)
    store.add_fact("Seu nome é Nathan", category="identity")
    llm = LLMClient(settings, transport=httpx.MockTransport(handler))
    app = create_app(settings=settings, memory_store=store, llm_client=llm)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # 1. Typing ativo e inativo.
            ws.send_json({"type": "typing", "active": True})
            assert ws.receive_json() == {"type": "state", "state": "listening"}

            ws.send_json({"type": "typing", "active": False})
            assert ws.receive_json() == {"type": "state", "state": "idle"}

            # 2. Mensagem vazia retorna erro sem chamar o LLM.
            ws.send_json({"type": "text", "text": "   "})
            err_empty = ws.receive_json()
            assert err_empty["type"] == "error"

            # 3. Envio de mensagem de texto válida.
            ws.send_json({"type": "text", "text": "Bom dia! Eu adoro café."})

            events = []
            while True:
                msg = ws.receive_json()
                events.append(msg)
                if msg["type"] == "memory_updated":
                    break

            types = [ev["type"] for ev in events]
            assert types[0] == "state"
            assert events[0]["state"] == "thinking"
            assert "emotion" in types
            assert "delta" in types
            assert "done" in types

            emotion_ev = next(ev for ev in events if ev["type"] == "emotion")
            assert emotion_ev["emotion"] == "happy"

            deltas_text = "".join(ev["text"] for ev in events if ev["type"] == "delta")
            assert "reasoning" not in deltas_text.lower()
            assert "pensar em pt-br" not in deltas_text.lower()
            assert "[emotion" not in deltas_text
            assert "[fact" not in deltas_text
            assert deltas_text.strip() == "Olá!"

            done_ev = next(ev for ev in events if ev["type"] == "done")
            assert done_ev["text"] == "Olá!"
            assert done_ev["emotion"] == "happy"
            assert any("café" in f["fact"].lower() for f in done_ev["facts"])

            mem_ev = events[-1]
            assert mem_ev["type"] == "memory_updated"
            assert mem_ev["recent_messages_count"] == 2
            assert any("Nathan" in f["fact"] for f in mem_ev["facts"])
            assert any("café" in f["fact"].lower() for f in mem_ev["facts"])

            # 4. Limpar histórico via WebSocket preserva fatos.
            ws.send_json({"type": "clear_history"})
            cleared = ws.receive_json()
            assert cleared["type"] == "memory_updated"
            assert cleared["recent_messages_count"] == 0
            assert len(cleared["facts"]) >= 2

    # Verifica contrato HTTP enviado ao provedor LLM.
    assert len(captured_requests) == 1
    req = captured_requests[0]
    assert req["url"] == "http://127.0.0.1:31415/v1/chat/completions"
    assert req["auth"] == "Bearer freellmapi-segredo-teste-123"
    assert req["json"]["stream"] is True
    assert req["json"]["max_tokens"] >= 500
    assert req["json"]["temperature"] == 0.7
    assert "Nathan" in req["json"]["messages"][0]["content"]

    store.close()


def test_websocket_erro_gracioso_sem_vazar_segredo(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Garante erro amigável no WS e ausência da API key nos logs e respostas."""
    secret = "freellmapi-chave-super-secreta-999"

    def failing_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            f"Falha ao conectar usando {secret}",
            request=request,
        )

    settings = _make_settings(tmp_path, api_key=secret)
    store = MemoryStore(db_path=settings.db_path)
    llm = LLMClient(settings, transport=httpx.MockTransport(failing_handler))
    app = create_app(settings=settings, memory_store=store, llm_client=llm)

    with caplog.at_level(logging.INFO):
        with TestClient(app) as client:
            with client.websocket_connect("/ws") as ws:
                ws.send_json({"type": "text", "text": "Olá!"})
                ev_thinking = ws.receive_json()
                ev_state_err = ws.receive_json()
                ev_err = ws.receive_json()

                assert ev_thinking == {"type": "state", "state": "thinking"}
                assert ev_state_err == {"type": "state", "state": "error"}
                assert ev_err["type"] == "error"
                assert "Não consegui falar com o modelo agora" in ev_err["message"]
                assert secret not in ev_err["message"]

    assert secret not in caplog.text
    assert "assistente" in build_system_prompt("Teste").lower()
    store.close()


def test_websocket_erro_http_500_gracioso(tmp_path: Path) -> None:
    """Garante tratamento amigável quando o provedor retorna HTTP 500."""

    def server_error_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "internal server error"})

    settings = _make_settings(tmp_path)
    store = MemoryStore(db_path=settings.db_path)
    llm = LLMClient(settings, transport=httpx.MockTransport(server_error_handler))
    app = create_app(settings=settings, memory_store=store, llm_client=llm)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "Teste erro 500"})
            assert ws.receive_json() == {"type": "state", "state": "thinking"}
            assert ws.receive_json() == {"type": "state", "state": "error"}
            err = ws.receive_json()
            assert err["type"] == "error"
            assert "Não consegui falar com o modelo agora" in err["message"]

    store.close()


def test_tag_stream_parser_tag_abreviada_e_colchete_comum() -> None:
    """Aceita forma abreviada `[<emocao>]` dividida em chunks e mantém `[nota]` no texto."""
    parser = TagStreamParser()
    eventos = []
    for chunk in ("[ha", "ppy] Olá! Veja ", "[nota]", " importante."):
        eventos.extend(parser.feed(chunk))
    finais, clean_text, _, emotion = parser.finish()
    eventos.extend(finais)

    assert emotion == "happy"
    assert eventos[0] == {"type": "emotion", "emotion": "happy"}
    assert clean_text == "Olá! Veja [nota] importante."
    deltas = "".join(ev["text"] for ev in eventos if ev["type"] == "delta")
    assert deltas == "Olá! Veja [nota] importante."
    assert "[happy]" not in deltas
