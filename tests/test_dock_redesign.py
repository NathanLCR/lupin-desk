"""Testes da issue 09 (Dock): Mac como único editor de Shortcuts e resposta no Active Body."""

from __future__ import annotations

import base64
import sys
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.llm import LLMClient
from app.main import create_app
from app.memory import MemoryStore
from app.shortcuts import ShortcutStore
from app.today import FirstWakeTracker
from app.tts import ServerTTS

IP_DO_MAC = "192.168.1.10"
IP_DE_OUTRO = "192.168.1.50"


def _settings(tmp_path: Path, **extra: Any) -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
        **extra,
    )


def _como_cliente(app: Any, host: str) -> Any:
    async def asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        patched = dict(scope)
        patched["client"] = (host, 54321)
        await app(patched, receive, send)

    return asgi


def _app_shortcuts(tmp_path: Path) -> Any:
    settings = _settings(tmp_path, desk_dev_sem_token=True)
    return create_app(settings=settings, local_ips=lambda: frozenset({IP_DO_MAC}))


NOVO = {"title": "Abrir Notas", "action_type": "app_activate", "payload": {"app": "Notes"}}


def test_client_info_diz_se_o_cliente_e_o_mac(tmp_path: Path) -> None:
    app = _app_shortcuts(tmp_path)
    with TestClient(app) as local:
        assert local.get("/api/client-info").json() == {"is_mac": True}
    with TestClient(_como_cliente(app, IP_DO_MAC)) as no_mac_pela_lan:
        assert no_mac_pela_lan.get("/api/client-info").json() == {"is_mac": True}
    with TestClient(_como_cliente(app, IP_DE_OUTRO)) as outro:
        assert outro.get("/api/client-info").json() == {"is_mac": False}


def test_escrita_de_shortcuts_so_no_mac_mesmo_sem_token(tmp_path: Path) -> None:
    app = _app_shortcuts(tmp_path)
    # Só o primeiro client roda o lifespan (e fecha o SQLite no fim).
    with TestClient(app) as mac:
        criado = mac.post("/api/shortcuts", json=NOVO)
        assert criado.status_code == 201
        sid = criado.json()["id"]

        outro = TestClient(_como_cliente(app, IP_DE_OUTRO))
        # Leitura continua liberada (dev sem token); escrita não.
        assert outro.get("/api/shortcuts").status_code == 200
        assert outro.post("/api/shortcuts", json=NOVO).status_code == 403
        assert outro.put(f"/api/shortcuts/{sid}", json={"title": "x"}).status_code == 403
        assert outro.put(f"/api/shortcuts/{sid}", json={"pinned_on_deck": True}).status_code == 403
        assert outro.delete(f"/api/shortcuts/{sid}").status_code == 403
        assert outro.post("/api/shortcuts/reorder", json={"ordered_ids": [sid]}).status_code == 403
        assert outro.post("/api/shortcuts/reset-defaults").status_code == 403

        mac_lan = TestClient(_como_cliente(app, IP_DO_MAC))
        assert mac_lan.put(f"/api/shortcuts/{sid}", json={"title": "Notas"}).status_code == 200
        assert mac_lan.delete(f"/api/shortcuts/{sid}").status_code == 200


def test_shortcut_novo_nasce_sem_fixar(tmp_path: Path) -> None:
    app = _app_shortcuts(tmp_path)
    with TestClient(app) as mac:
        criado = mac.post("/api/shortcuts", json=NOVO).json()
        assert criado["pinned_on_deck"] is False
        fixado = mac.put(f"/api/shortcuts/{criado['id']}", json={"pinned_on_deck": True}).json()
        assert fixado["pinned_on_deck"] is True
    store = ShortcutStore(db_path=tmp_path / "direto.db")
    try:
        assert store.create_shortcut(NOVO)["pinned_on_deck"] is False
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Roteamento da resposta para o Active Body
# ---------------------------------------------------------------------------


def _app_ws(tmp_path: Path, synth: Any, *, hora: int = 3, stt: Any = None) -> Any:
    settings = _settings(tmp_path)

    async def fake_stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "emotion", "emotion": "happy"}
        yield {"type": "delta", "text": "Oi!"}
        yield {"type": "sentence", "text": "Oi!"}
        yield {"type": "sentence", "text": "Tudo bem?"}
        yield {
            "type": "result",
            "text": "Oi! Tudo bem?",
            "raw_text": "Oi! Tudo bem?",
            "emotion": "happy",
        }

    memory = MemoryStore(db_path=settings.db_path)
    return create_app(
        settings=settings,
        memory_store=memory,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        tts_engine=ServerTTS(synth_fn=synth),
        stt_engine=stt,
        first_wake=FirstWakeTracker(memory, clock=lambda: datetime(2026, 11, 17, hora, 0)),
        agenda_reader=lambda: [],
    )


def _hello(ws: Any, body: str, audio: bool = False) -> dict[str, Any]:
    ws.send_json({"type": "hello", "body": body, "protocol": 1, "audio": ["m4a"] if audio else []})
    return ws.receive_json()


def _ate(ws: Any, tipo: str) -> list[dict[str, Any]]:
    eventos = []
    while True:
        ev = ws.receive_json()
        eventos.append(ev)
        if ev["type"] == tipo:
            return eventos


async def _synth_ok(text: str, voice: str, fmt: str) -> bytes:
    return b"voz:" + text.encode()


def _audios_ate_ultima(ws: Any, frases: int) -> list[dict[str, Any]]:
    audios: list[dict[str, Any]] = []
    while len([a for a in audios if a["last"]]) < frases:
        ev = ws.receive_json()
        assert ev["type"] == "audio", ev
        audios.append(ev)
    return audios


def test_pergunta_do_inativo_vai_como_texto_e_voz_no_active_body(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=True)
            assert _hello(rg, "rg406h-web", audio=True)["active"] is False
            rg.send_json({"type": "text", "text": "oi"})

            # Quem perguntou: só texto, sem áudio e sem from_body.
            eventos_rg = _ate(rg, "memory_updated")
            tipos = [e["type"] for e in eventos_rg]
            assert tipos[0] == "state"
            assert [e["text"] for e in eventos_rg if e["type"] == "sentence"] == ["Oi!", "Tudo bem?"]
            assert "done" in tipos and "audio" not in tipos
            assert not any("from_body" in e for e in eventos_rg)

            # Active Body: expressão, frases, done e voz, todos com from_body.
            eventos_esp = _ate(esp, "done")
            assert [e["type"] for e in eventos_esp] == ["emotion", "sentence", "sentence", "done"]
            assert all(e["from_body"] == "rg406h-web" for e in eventos_esp)
            assert eventos_esp[0]["emotion"] == "happy"
            assert eventos_esp[-1]["text"] == "Oi! Tudo bem?"
            audios = _audios_ate_ultima(esp, 2)
            assert all(a["from_body"] == "rg406h-web" for a in audios)
            voz = {
                a["sentence"]: base64.b64decode(a["data"]) for a in audios if a["last"]
            }
            assert voz == {0: b"voz:Oi!", 1: b"voz:Tudo bem?"}


def test_pergunta_por_audio_do_inativo_tambem_espelha(tmp_path: Path) -> None:
    class _Stt:
        async def transcribe_bytes(self, **kwargs: Any) -> dict[str, Any]:
            return {"text": "oi", "engine": "fake"}

    app = _app_ws(tmp_path, _synth_ok, stt=_Stt())
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=True)
            _hello(rg, "rg406h-web", audio=True)
            rg.send_json({"type": "audio", "data": base64.b64encode(b"abc").decode(), "mime_type": "audio/webm"})
            eventos_rg = _ate(rg, "memory_updated")
            assert "transcript" in [e["type"] for e in eventos_rg]
            assert not [e for e in eventos_rg if e["type"] == "audio"]
            eventos_esp = _ate(esp, "done")
            assert all(e["from_body"] == "rg406h-web" for e in eventos_esp)
            assert "transcript" not in [e["type"] for e in eventos_esp]


def test_active_body_sem_audio_declarado_recebe_so_o_texto(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        raise AssertionError("TTS não deveria ser chamado")

    with TestClient(_app_ws(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=False)
            _hello(rg, "rg406h-web", audio=True)
            rg.send_json({"type": "text", "text": "oi"})
            _ate(rg, "memory_updated")
            eventos_esp = _ate(esp, "done")
            assert all(e["from_body"] == "rg406h-web" for e in eventos_esp)
            esp.send_json({"type": "typing", "active": False})
            assert esp.receive_json() == {"type": "state", "state": "idle"}


def test_quem_pergunta_sendo_o_active_body_nada_muda(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=True)
            _hello(rg, "rg406h-web", audio=True)
            esp.send_json({"type": "text", "text": "oi"})
            eventos = _ate(esp, "memory_updated")
            assert not any("from_body" in e for e in eventos)
            _audios_ate_ultima(esp, 2)
            # O Dock não recebe nada da conversa do Active Body.
            rg.send_json({"type": "typing", "active": False})
            assert rg.receive_json() == {"type": "state", "state": "idle"}


def test_sem_active_body_so_o_texto_volta_para_quem_perguntou(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "text", "text": "oi"})  # sem hello: não é Body nenhum
        eventos = _ate(ws, "memory_updated")
        assert "done" in [e["type"] for e in eventos]
        assert not [e for e in eventos if e["type"] in ("audio",)]
        assert not any("from_body" in e for e in eventos)


def test_active_body_que_sai_no_meio_nao_derruba_o_turno_de_quem_perguntou(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client:
        with client.websocket_connect("/ws") as rg:
            with client.websocket_connect("/ws") as esp:
                _hello(esp, "esp32", audio=True)
                assert _hello(rg, "rg406h-web", audio=True)["active"] is False
            # ESP32 fechou antes da pergunta: o RG406H volta a ser o Active Body e nada quebra.
            assert rg.receive_json() == {"type": "active_body", "active_body": "rg406h-web", "active": True}
            rg.send_json({"type": "text", "text": "oi"})
            eventos = _ate(rg, "memory_updated")
            assert "done" in [e["type"] for e in eventos]


def test_mirror_para_conexao_morta_e_ignorado(tmp_path: Path) -> None:
    app = _app_ws(tmp_path, _synth_ok)
    with TestClient(app) as client, client.websocket_connect("/ws") as rg:
        _hello(rg, "rg406h-web", audio=True)
        # Simula um Active Body (esp32) cuja conexão já caiu mas ainda está registrado.
        async def morto(payload: dict[str, Any]) -> None:
            raise RuntimeError("socket fechado")

        app.state.bodies.append({"body": "esp32", "seq": 999, "send": morto, "wants_audio": True})
        rg.send_json({"type": "text", "text": "oi"})
        eventos = _ate(rg, "memory_updated")
        assert "done" in [e["type"] for e in eventos]
        assert "error" not in [e["type"] for e in eventos]


def test_first_wake_marca_cada_frase(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok, hora=7)) as client, client.websocket_connect("/ws") as ws:
        _hello(ws, "rg406h-web")
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        eventos = _ate(ws, "done")
        frases = [e for e in eventos if e["type"] == "sentence"]
        assert len(frases) >= 2
        assert all(f["first_wake"] is True for f in frases)
        assert eventos[-1]["first_wake"] is True


def test_resposta_normal_nao_leva_first_wake(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client, client.websocket_connect("/ws") as ws:
        _hello(ws, "rg406h-web")
        ws.send_json({"type": "text", "text": "oi"})
        eventos = _ate(ws, "memory_updated")
        assert not any("first_wake" in e for e in eventos if e["type"] == "sentence")


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_loopback_conta_como_mac(tmp_path: Path, host: str) -> None:
    app = _app_shortcuts(tmp_path)
    with TestClient(_como_cliente(app, host)) as c:
        assert c.get("/api/client-info").json() == {"is_mac": True}
