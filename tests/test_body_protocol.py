"""Testes do protocolo Brain<->Body v1 (docs/protocolo-cerebro-corpo.md)."""

from __future__ import annotations

import base64
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.llm import LLMClient
from app.main import create_app
from app.tts import ServerTTS


def _app(tmp_path: Path, synth: Any) -> Any:
    settings = Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
    )

    async def fake_stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "sentence", "text": "Oi!"}
        yield {"type": "sentence", "text": "Tudo bem?"}
        yield {
            "type": "result",
            "text": "Oi! Tudo bem?",
            "raw_text": "Oi! Tudo bem?",
            "emotion": "neutral",
        }

    return create_app(
        settings=settings,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        tts_engine=ServerTTS(synth_fn=synth),
    )


def _turn(ws: Any) -> list[dict[str, Any]]:
    """Envia um texto e coleta eventos até `done` e o último `audio` esperado."""
    ws.send_json({"type": "text", "text": "oi"})
    events: list[dict[str, Any]] = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] == "memory_updated":
            return events


def test_hello_recebe_welcome(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "esp32", "protocol": 1, "audio": ["m4a"]})
        assert ws.receive_json() == {
            "type": "welcome",
            "protocol": 1,
            "active_body": "esp32",
            "active": True,
        }


def test_touch_devolve_mood(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "touch", "kind": "pet", "intensity": 1.0})
        ev = ws.receive_json()
        assert ev["type"] == "mood"
        assert ev["kind"] == "pet"
        assert "affinity" in ev and "energy" in ev


def test_audio_em_chunks_apos_sentence(tmp_path: Path) -> None:
    payloads = {"Oi!": b"a" * (24 * 1024 + 10), "Tudo bem?": b"b" * 5}

    async def synth(text: str, voice: str, fmt: str) -> bytes:
        assert fmt == "m4a"
        return payloads[text]

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1, "audio": ["m4a"]})
        ws.receive_json()
        events = _turn(ws)
        # Drena os chunks que chegam após memory_updated.
        audio = [e for e in events if e["type"] == "audio"]
        while not audio or not (audio[-1]["sentence"] == 1 and audio[-1]["last"]):
            audio.append(ws.receive_json())

    by_sentence: dict[int, list[dict[str, Any]]] = {0: [], 1: []}
    for ev in audio:
        assert ev["mime"] == "audio/mp4"
        by_sentence[ev["sentence"]].append(ev)
    assert [e["seq"] for e in by_sentence[0]] == [0, 1]
    assert [e["last"] for e in by_sentence[0]] == [False, True]
    assert b"".join(base64.b64decode(e["data"]) for e in by_sentence[0]) == payloads["Oi!"]
    assert len(base64.b64decode(by_sentence[0][0]["data"])) <= 24 * 1024
    assert [e["last"] for e in by_sentence[1]] == [True]
    assert base64.b64decode(by_sentence[1][0]["data"]) == payloads["Tudo bem?"]


def test_sem_audio_quando_hello_nao_pede(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        raise AssertionError("TTS não deveria ser chamado")

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        events = _turn(ws)
    assert not [e for e in events if e["type"] == "audio"]


def test_falha_de_tts_nao_quebra_turno(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        raise RuntimeError("say indisponível")

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "esp32", "protocol": 1, "audio": ["m4a"]})
        ws.receive_json()
        events = _turn(ws)
        # Conexão segue saudável depois da falha.
        ws.send_json({"type": "touch", "kind": "poke"})
        assert ws.receive_json()["type"] == "mood"
    types = [e["type"] for e in events]
    assert "done" in types
    assert "audio" not in types and "error" not in types


def _hello(ws: Any, body: str, audio: bool = False) -> dict[str, Any]:
    ws.send_json({"type": "hello", "body": body, "protocol": 1, "audio": ["m4a"] if audio else []})
    return ws.receive_json()


def test_esp32_tira_o_lupin_do_rg406h_e_devolve_ao_sair(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as rg:
            assert _hello(rg, "rg406h-web")["active"] is True
            with client.websocket_connect("/ws") as esp:
                welcome = _hello(esp, "esp32")
                assert welcome["active"] is True
                aviso = rg.receive_json()
                assert aviso == {"type": "active_body", "active_body": "esp32", "active": False}
            # ESP32 saiu: o RG406H volta a ser o Active Body.
            assert rg.receive_json() == {"type": "active_body", "active_body": "rg406h-web", "active": True}


def test_navegador_comum_nao_rouba_o_lupin_do_rg406h(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as rg, client.websocket_connect("/ws") as mac:
            _hello(rg, "rg406h-web")
            welcome = _hello(mac, "web")
            assert welcome["active"] is False and welcome["active_body"] == "rg406h-web"


def test_mesmo_tipo_o_ultimo_a_chegar_fica_com_o_lupin(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            _hello(a, "web")
            assert _hello(b, "web")["active"] is True
            assert a.receive_json()["active"] is False


def test_body_inativo_nao_recebe_a_voz(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=True)
            assert _hello(rg, "rg406h-web", audio=True)["active"] is False
            events = _turn(rg)
    assert "done" in [e["type"] for e in events]
    assert not [e for e in events if e["type"] == "audio"]
