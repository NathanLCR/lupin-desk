"""Testes de API HTTP, WebSocket, ações Mac, STT/TTS e streaming LLM para o Desk Assistant."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.llm import SUPPORTED_EMOTIONS, LLMClient, TagStreamParser, build_system_prompt
from app.mac_control import MacController
from app.main import create_app
from app.memory import MemoryStore
from app.shortcuts import ShortcutStore
from app.stt import LocalSTT
from app.tts import ServerTTS


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


def _make_mock_mac(recorded_calls: list[list[str]] | None = None) -> MacController:
    """Cria MacController com subprocess e clima simulados para testes rápidos e seguros."""

    def runner(argv: list[str], timeout: float = 5.0) -> subprocess.CompletedProcess[str]:
        if recorded_calls is not None:
            recorded_calls.append(list(argv))
        if argv and argv[0] == "/usr/bin/osascript":
            script = argv[-1]
            if "every application process" in script:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="Google Chrome||true\nTerminal||false\n",
                    stderr="",
                )
            if "get volume settings" in script:
                return subprocess.CompletedProcess(
                    args=argv,
                    returncode=0,
                    stdout="Google Chrome||55||false||Spotify||playing||Lofi Beat||Chilled",
                    stderr="",
                )
        if argv and argv[0] == "/usr/bin/pmset":
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="Now drawing from 'Battery Power'\n -InternalBattery-0\t88%; discharging; 4:10 remaining",
                stderr="",
            )
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    def weather_fetcher(lat: float, lon: float, city: str) -> dict[str, Any]:
        return {
            "current": {
                "temperature_2m": 24.5,
                "apparent_temperature": 25.0,
                "weather_code": 0,
                "wind_speed_10m": 8.0,
                "is_day": 1,
            }
        }

    return MacController(runner=runner, weather_fetcher=weather_fetcher)


# ----------------------------------------------------------------------
# Testes da Fase 1 (Preservados integralmente)
# ----------------------------------------------------------------------


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
    app = create_app(
        settings=settings,
        memory_store=store,
        llm_client=LLMClient(settings),
        mac_controller=_make_mock_mac(),
    )

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
    app = create_app(
        settings=settings,
        memory_store=store,
        llm_client=llm,
        mac_controller=_make_mock_mac(),
    )

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
    app = create_app(
        settings=settings,
        memory_store=store,
        llm_client=llm,
        mac_controller=_make_mock_mac(),
    )

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
    app = create_app(
        settings=settings,
        memory_store=store,
        llm_client=llm,
        mac_controller=_make_mock_mac(),
    )

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


# ----------------------------------------------------------------------
# Novos Testes da Fase 2 (Ações, Sentenças, Barge-in, Voz e Endpoints)
# ----------------------------------------------------------------------


def test_tag_stream_parser_actions_sentences_e_12_emocoes() -> None:
    """Valida 12 emoções, emissão incremental de sentenças e parsing de `[action:...]`."""
    assert len(SUPPORTED_EMOTIONS) == 12
    assert "angry" in SUPPORTED_EMOTIONS
    assert "dizzy" in SUPPORTED_EMOTIONS

    parser = TagStreamParser()
    chunks = [
        "[emotion:angry] Ei! ",
        "[act",
        "ion:shortcut:find_replace]",
        " Versão 3.14 pronta. ",
        "[action:app:Google Chrome]",
        " Agora foco total",
        "[action:pomodoro:start]",
    ]
    eventos: list[dict[str, str]] = []
    for chunk in chunks:
        eventos.extend(parser.feed(chunk))
    finais, clean_text, _, emotion = parser.finish()
    eventos.extend(finais)

    assert emotion == "angry"
    assert clean_text == "Ei!  Versão 3.14 pronta.  Agora foco total"

    actions = [ev for ev in eventos if ev["type"] == "action"]
    assert actions == [
        {"type": "action", "kind": "shortcut", "target": "find_replace"},
        {"type": "action", "kind": "app", "target": "Google Chrome"},
        {"type": "action", "kind": "pomodoro", "target": "start"},
    ]

    sentences = [ev["text"] for ev in eventos if ev["type"] == "sentence"]
    assert sentences == ["Ei!", "Versão 3.14 pronta.", "Agora foco total"]
    assert "[action" not in clean_text


def test_build_system_prompt_injeta_atalhos_e_regras() -> None:
    """Garante que o prompt inclui catálogo de atalhos, humor, âncora temporal e Show Don't Tell."""
    prompt = build_system_prompt(
        memory_context="- Prefere tema escuro",
        shortcuts_context="- [find_replace] Pesquisar e Substituir",
        companion_context="Estado do pet: humor animado",
        temporal_context="Período do dia: noite (22:15).",
    )
    assert "Show, Don't Tell" in prompt or "SHOW, DON'T TELL" in prompt
    assert "[action:shortcut:<slug>]" in prompt
    assert "Prefere tema escuro" in prompt
    assert "find_replace" in prompt
    assert "humor animado" in prompt
    assert "22:15" in prompt


def test_http_novos_endpoints_shortcuts_mac_tts_stt_diagnostics(tmp_path: Path) -> None:
    """Testa todas as novas rotas REST adicionadas na Fase 2."""
    secret = "freellmapi-segredo-nao-vazar"
    settings = _make_settings(tmp_path, api_key=secret)
    memory = MemoryStore(db_path=settings.db_path)
    shortcuts = ShortcutStore(db_path=settings.db_path)
    recorded_calls: list[list[str]] = []
    mac = _make_mock_mac(recorded_calls)

    stt = LocalSTT(
        transcribe_fn=lambda audio, mime, lang: {
            "text": f"transcrito ({len(audio)}b, {lang})",
            "available": True,
            "engine": "custom",
            "error": None,
        }
    )
    tts = ServerTTS(
        default_voice="Luciana",
        synth_fn=lambda text, voice, fmt: (
            b"FAKEAUDIO-" + fmt.encode("utf-8"),
            "audio/mp4" if fmt == "m4a" else "audio/wav",
        ),
        runner=lambda argv, **kwargs: subprocess.CompletedProcess(
            args=argv,
            returncode=0,
            stdout="Luciana             pt_BR    # Olá, meu nome é Luciana.\nDaniel              en_GB    # Hello.\n",
            stderr="",
        ),
    )

    app = create_app(
        settings=settings,
        memory_store=memory,
        llm_client=LLMClient(settings),
        shortcut_store=shortcuts,
        mac_controller=mac,
        stt_engine=stt,
        tts_engine=tts,
    )

    with TestClient(app) as client:
        # Manifest PWA
        res_manifest = client.get("/manifest.json")
        assert res_manifest.status_code == 200
        assert res_manifest.json()["short_name"] == "EMO Desk"

        # Memória expandida: /api/memory/state, PATCH pinned/importance, consolidate
        fact = client.post("/api/memory/facts", json={"fact": "Gosta de café"}).json()
        res_patch = client.patch(
            f"/api/memory/facts/{fact['id']}",
            json={"pinned": True, "importance": 9},
        )
        assert res_patch.status_code == 200
        assert res_patch.json()["pinned"] is True
        assert res_patch.json()["importance"] == 9
        assert client.patch("/api/memory/facts/99999", json={"pinned": True}).status_code == 404

        res_state = client.get("/api/memory/state")
        assert res_state.status_code == 200
        state_body = res_state.json()
        assert "companion" in state_body
        assert "temporal" in state_body

        res_cons = client.post("/api/memory/consolidate")
        assert res_cons.status_code == 200
        assert "consolidated" in res_cons.json()

        # Atalhos CRUD + Run + Reorder + Reset
        res_sc_list = client.get("/api/shortcuts")
        assert res_sc_list.status_code == 200
        initial_shortcuts = res_sc_list.json()["shortcuts"]
        assert any(s["slug"] == "find_replace" for s in initial_shortcuts)

        res_sc_new = client.post(
            "/api/shortcuts",
            json={
                "title": "Abrir Notas",
                "icon": "📝",
                "category": "apps",
                "action_type": "app_activate",
                "payload": {"app": "Notes"},
                "voice_triggers": "notas, abrir notas",
            },
        )
        assert res_sc_new.status_code == 201
        created_sc = res_sc_new.json()
        assert created_sc["slug"] == "abrir_notas"

        res_sc_upd = client.put(
            f"/api/shortcuts/{created_sc['id']}",
            json={"title": "Notas Rápidas"},
        )
        assert res_sc_upd.status_code == 200
        assert res_sc_upd.json()["title"] == "Notas Rápidas"

        res_sc_run = client.post("/api/shortcuts/find_replace/run")
        assert res_sc_run.status_code == 200
        assert res_sc_run.json()["ok"] is True
        assert any("osascript" in call[0] for call in recorded_calls)

        res_sc_reord = client.post(
            "/api/shortcuts/reorder",
            json={"ordered_ids": [created_sc["id"], "find_replace"]},
        )
        assert res_sc_reord.status_code == 200
        assert res_sc_reord.json()["shortcuts"][0]["id"] == created_sc["id"]

        res_sc_del = client.delete(f"/api/shortcuts/{created_sc['id']}")
        assert res_sc_del.status_code == 200
        assert client.delete(f"/api/shortcuts/{created_sc['id']}").status_code == 404

        res_sc_reset = client.post("/api/shortcuts/reset-defaults")
        assert res_sc_reset.status_code == 200
        assert any(s["slug"] == "find_replace" for s in res_sc_reset.json()["shortcuts"])

        # Mac Dock Viva, Status e Clima
        res_apps = client.get("/api/mac/apps")
        assert res_apps.status_code == 200
        assert any(a["name"] == "Google Chrome" and a["frontmost"] for a in res_apps.json()["apps"])

        res_act_bad = client.post("/api/mac/apps/activate", json={"app": "Safari; rm -rf /"})
        assert res_act_bad.status_code == 400
        assert res_act_bad.json()["ok"] is False

        res_act_ok = client.post("/api/mac/apps/activate", json={"app": "Safari"})
        assert res_act_ok.status_code == 200
        assert res_act_ok.json()["ok"] is True

        res_status = client.get("/api/mac/status")
        assert res_status.status_code == 200
        assert res_status.json()["active_app"] == "Google Chrome"
        assert res_status.json()["battery_percent"] == 88

        res_weather = client.get("/api/weather")
        assert res_weather.status_code == 200
        assert res_weather.json()["ok"] is True
        assert res_weather.json()["effect"] == "sun"

        # TTS
        res_voices = client.get("/api/tts/voices")
        assert res_voices.status_code == 200
        assert res_voices.json()["voices"][0]["name"] == "Luciana"

        res_tts_m4a = client.post("/api/tts", json={"text": "Olá Nathan", "format": "m4a"})
        assert res_tts_m4a.status_code == 200
        assert res_tts_m4a.headers["content-type"].startswith("audio/mp4")
        assert res_tts_m4a.content == b"FAKEAUDIO-m4a"

        res_tts_wav = client.post("/api/tts", json={"text": "Olá Nathan", "format": "wav"})
        assert res_tts_wav.status_code == 200
        assert res_tts_wav.headers["content-type"].startswith("audio/wav")

        assert client.post("/api/tts", json={"text": "   "}).status_code == 400

        # STT (JSON base64 e multipart)
        b64_audio = base64.b64encode(b"WEBM_BYTES").decode("ascii")
        res_stt_json = client.post(
            "/api/stt",
            json={"data": b64_audio, "mime_type": "audio/webm", "language": "pt"},
        )
        assert res_stt_json.status_code == 200
        assert "10b" in res_stt_json.json()["text"]

        res_stt_mp = client.post(
            "/api/stt",
            files={"file": ("gravacao.webm", b"AUDIO123456", "audio/webm")},
            data={"language": "pt"},
        )
        assert res_stt_mp.status_code == 200
        assert "11b" in res_stt_mp.json()["text"]

        # Diagnósticos (sem vazar LLM_API_KEY)
        res_diag = client.get("/api/diagnostics")
        assert res_diag.status_code == 200
        diag = res_diag.json()
        assert diag["stt_available"] is True
        assert diag["tts_available"] is True
        assert diag["https_port"] == 8443
        assert secret not in json.dumps(diag)

    shortcuts.close()
    memory.close()


def test_websocket_action_tags_sentences_e_confirmacao(tmp_path: Path) -> None:
    """Valida execução de `[action:shortcut:find_replace]`, `[action:app:...]`, `sentence` e confirmação."""
    recorded_calls: list[list[str]] = []
    sse_payload = _build_sse_stream(
        [
            {"choices": [{"delta": {"content": "[emotion:wink] Abrindo substituir! "}}]},
            {"choices": [{"delta": {"content": "[action:shortcut:find_replace] "}}]},
            {"choices": [{"delta": {"content": "[action:app:Safari] "}}]},
            {"choices": [{"delta": {"content": "[action:pomodoro:start] Tudo pronto."}}]},
        ]
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=sse_payload,
        )

    settings = _make_settings(tmp_path)
    memory = MemoryStore(db_path=settings.db_path)
    shortcuts = ShortcutStore(db_path=settings.db_path)
    shortcuts.create_shortcut(
        {
            "slug": "acao_sensivel",
            "title": "Ação Sensível",
            "action_type": "mac_command",
            "payload": {"command": "lock_screen"},
            "requires_confirmation": True,
        }
    )
    mac = _make_mock_mac(recorded_calls)
    llm = LLMClient(settings, transport=httpx.MockTransport(handler))
    app = create_app(
        settings=settings,
        memory_store=memory,
        llm_client=llm,
        shortcut_store=shortcuts,
        mac_controller=mac,
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "Pesquisar e substituir e abrir Safari"})
            events = []
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] == "memory_updated":
                    break

            sentences = [ev["text"] for ev in events if ev["type"] == "sentence"]
            assert sentences == ["Abrindo substituir!", "Tudo pronto."]

            actions = [ev for ev in events if ev["type"] == "action_executed"]
            assert any(
                a["kind"] == "shortcut" and a["target"] == "find_replace" and a["ok"] is True
                for a in actions
            )
            app_approval = next(
                ev for ev in events
                if ev.get("type") == "tool_approval_request"
                and ev.get("kind") == "mac_app"
                and ev.get("target") == "Safari"
            )
            ws.send_json({"type": "confirm_action", "approval_id": app_approval["approval_id"], "approved": True})
            app_done = ws.receive_json()
            assert app_done["kind"] == "app" and app_done["target"] == "Safari" and app_done["ok"] is True
            assert any(
                a["kind"] == "pomodoro" and a["command"] == "pomodoro_start" and a["ok"] is True
                for a in actions
            )
            assert any(
                call[0] == "/usr/bin/osascript" and "option down" in call[-1] and '"f"' in call[-1]
                for call in recorded_calls
            )
            assert any(
                call[:3] == ["/usr/bin/open", "-a", "Safari"] for call in recorded_calls
            )

            # Testa atalho com `requires_confirmation=True` via LLM mockado
            async def approval_stream(**_kwargs):
                yield {"type": "emotion", "emotion": "curious"}
                yield {"type": "action", "kind": "shortcut", "target": "acao_sensivel"}
                yield {"type": "delta", "text": "Posso bloquear a tela?"}
                yield {"type": "sentence", "text": "Posso bloquear a tela?"}
                yield {
                    "type": "result",
                    "text": "Posso bloquear a tela?",
                    "raw_text": "Posso bloquear a tela?",
                    "emotion": "curious",
                }

            app.state.llm._stream_fn = approval_stream
            ws.send_json({"type": "text", "text": "Bloqueia a tela"})
            approval_req = None
            while True:
                ev = ws.receive_json()
                if ev["type"] == "tool_approval_request":
                    approval_req = ev
                if ev["type"] == "memory_updated":
                    break

            assert approval_req is not None
            assert approval_req["target"] == "acao_sensivel"

            ws.send_json(
                {
                    "type": "confirm_action",
                    "approval_id": approval_req["approval_id"],
                    "approved": True,
                }
            )
            confirm_res = ws.receive_json()
            assert confirm_res["type"] == "action_executed"
            assert confirm_res["target"] == "acao_sensivel"
            assert confirm_res["ok"] is True

    shortcuts.close()
    memory.close()


def test_websocket_barge_in_interrupt_e_audio_pet(tmp_path: Path) -> None:
    """Valida interrupção imediata (barge-in), áudio STT -> LLM, pet, run_shortcut e activate_app."""

    async def slow_or_fast_stream(user_text: str, **_kwargs):
        if "lento" in user_text.lower():
            yield {"type": "emotion", "emotion": "happy"}
            yield {"type": "delta", "text": "Começando uma história muito longa..."}
            await asyncio.sleep(5.0)
            yield {
                "type": "result",
                "text": "Fim",
                "raw_text": "Fim",
                "emotion": "happy",
            }
            return

        yield {"type": "emotion", "emotion": "love"}
        yield {"type": "delta", "text": "Entendi perfeitamente!"}
        yield {"type": "sentence", "text": "Entendi perfeitamente!"}
        yield {
            "type": "result",
            "text": "Entendi perfeitamente!",
            "raw_text": "Entendi perfeitamente!",
            "emotion": "love",
        }

    settings = _make_settings(tmp_path)
    memory = MemoryStore(db_path=settings.db_path)
    shortcuts = ShortcutStore(db_path=settings.db_path)
    mac = _make_mock_mac()
    llm = LLMClient(settings, stream_fn=slow_or_fast_stream)
    stt = LocalSTT(
        transcribe_fn=lambda audio, mime, lang: {
            "text": "Oi robozinho",
            "available": True,
            "engine": "custom",
            "error": None,
        }
    )

    app = create_app(
        settings=settings,
        memory_store=memory,
        llm_client=llm,
        shortcut_store=shortcuts,
        mac_controller=mac,
        stt_engine=stt,
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            # 1. Barge-in (interrupt) cancela streaming lento sem travar
            ws.send_json({"type": "text", "text": "Modo lento por favor"})
            assert ws.receive_json() == {"type": "state", "state": "thinking"}
            assert ws.receive_json() == {"type": "emotion", "emotion": "happy"}
            assert ws.receive_json()["type"] == "delta"

            ws.send_json({"type": "interrupt"})
            interrupted_events = [ws.receive_json(), ws.receive_json()]
            assert {"type": "interrupted"} in interrupted_events
            assert {"type": "state", "state": "idle"} in interrupted_events

            # 2. Carinho (pet) aumenta afinidade
            ws.send_json({"type": "pet", "kind": "pet", "intensity": 1.0})
            pet_ev = ws.receive_json()
            assert pet_ev["type"] == "companion_updated"
            assert pet_ev["affinity"] > 50.0

            # 3. Atalho direto e ativar app via WS
            ws.send_json({"type": "run_shortcut", "id": "find_replace"})
            sc_ev = ws.receive_json()
            assert sc_ev["type"] == "action_executed"
            assert sc_ev["target"] == "find_replace"
            assert sc_ev["ok"] is True

            ws.send_json({"type": "activate_app", "app": "Finder"})
            app_ev = ws.receive_json()
            assert app_ev["type"] == "action_executed"
            assert app_ev["kind"] == "app"
            assert app_ev["ok"] is True

            # 4. Áudio base64 -> transcript -> turno LLM
            audio_b64 = base64.b64encode(b"FAKE_WEBM_AUDIO").decode("ascii")
            ws.send_json({"type": "audio", "data": audio_b64, "mime_type": "audio/webm"})
            audio_events = []
            while True:
                ev = ws.receive_json()
                audio_events.append(ev)
                if ev["type"] == "memory_updated":
                    break
            assert any(
                ev["type"] == "transcript" and ev["text"] == "Oi robozinho" for ev in audio_events
            )
            assert any(ev["type"] == "done" and ev["emotion"] == "love" for ev in audio_events)

    shortcuts.close()
    memory.close()


@pytest.mark.asyncio
async def test_stt_tts_fallback_e_seguranca_subprocess() -> None:
    """Valida LocalSTT com fallback seguro e ServerTTS usando exclusivamente lista argv."""
    stt_missing = LocalSTT()
    if not stt_missing.is_available():
        res = await stt_missing.transcribe_bytes(b"1234", mime_type="audio/webm", language="pt")
        assert res["available"] is False
        assert res["text"] == ""
        assert res["error"]

    stt_empty = LocalSTT(transcribe_fn=lambda *_args: "ok")
    empty_res = await stt_empty.transcribe_bytes(b"", mime_type="audio/webm", language="pt")
    assert empty_res["error"]

    seen_argvs: list[tuple[list[str], bool]] = []

    def fake_runner(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        seen_argvs.append((list(argv), bool(kwargs.get("shell", False))))
        if "-v" in argv and "?" in argv:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=0,
                stdout="Daniel              en_GB    # Hello.\nLuciana             pt_BR    # Olá!\n",
                stderr="",
            )
        if argv[0] == "/usr/bin/afconvert":
            Path(argv[-1]).write_bytes(b"M4A_BYTES")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout="", stderr="")

    tts = ServerTTS(default_voice="Luciana", runner=fake_runner)
    voices = tts.list_voices()
    assert voices[0]["name"] == "Luciana"
    assert voices[0]["locale"] == "pt_BR"

    audio, mime = tts.synthesize("Olá mundo!", voice="Luciana", output_format="m4a")
    assert audio == b"M4A_BYTES"
    assert mime == "audio/mp4"
    assert all(shell_flag is False for _, shell_flag in seen_argvs)
    assert any(argv[0] == "/usr/bin/say" for argv, _ in seen_argvs)
    assert any(argv[0] == "/usr/bin/afconvert" for argv, _ in seen_argvs)
