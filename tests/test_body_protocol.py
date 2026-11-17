"""Tests for the Brain<->Body v1 protocol (docs/brain-body-protocol.md)."""

from __future__ import annotations

import base64
import sys
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.llm import LLMClient
from app.main import create_app
from app.memory import MemoryStore
from app.today import FirstWakeTracker
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

    memory = MemoryStore(db_path=settings.db_path)
    return create_app(
        settings=settings,
        memory_store=memory,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        tts_engine=ServerTTS(synth_fn=synth),
        # Before 5am: First Wake does not enter the turns of these tests.
        first_wake=FirstWakeTracker(memory, clock=lambda: datetime(2026, 11, 17, 3, 0)),
    )


def _turn(ws: Any) -> list[dict[str, Any]]:
    """Send a text and collect events up to `done` and the last expected `audio`."""
    ws.send_json({"type": "text", "text": "oi"})
    events: list[dict[str, Any]] = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] == "memory_updated":
            return events


def test_hello_receives_welcome(tmp_path: Path) -> None:
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


def test_touch_returns_mood(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "touch", "kind": "pet", "intensity": 1.0})
        ev = ws.receive_json()
        assert ev["type"] == "mood"
        assert ev["kind"] == "pet"
        assert "affinity" in ev and "energy" in ev


def test_audio_in_chunks_after_sentence(tmp_path: Path) -> None:
    payloads = {"Oi!": b"a" * (24 * 1024 + 10), "Tudo bem?": b"b" * 5}

    async def synth(text: str, voice: str, fmt: str) -> bytes:
        assert fmt == "m4a"
        return payloads[text]

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1, "audio": ["m4a"]})
        ws.receive_json()
        events = _turn(ws)
        # Drain the chunks that arrive after memory_updated.
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


def test_no_audio_when_hello_does_not_ask(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        raise AssertionError("TTS should not be called")

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        events = _turn(ws)
    assert not [e for e in events if e["type"] == "audio"]


def test_tts_failure_does_not_break_turn(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        raise RuntimeError("say unavailable")

    with TestClient(_app(tmp_path, synth)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "esp32", "protocol": 1, "audio": ["m4a"]})
        ws.receive_json()
        events = _turn(ws)
        # The connection stays healthy after the failure.
        ws.send_json({"type": "touch", "kind": "poke"})
        assert ws.receive_json()["type"] == "mood"
    types = [e["type"] for e in events]
    assert "done" in types
    assert "audio" not in types and "error" not in types


def _hello(ws: Any, body: str, audio: bool = False) -> dict[str, Any]:
    ws.send_json({"type": "hello", "body": body, "protocol": 1, "audio": ["m4a"] if audio else []})
    return ws.receive_json()


def test_esp32_takes_lupin_from_rg406h_and_gives_it_back_on_exit(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as rg:
            assert _hello(rg, "rg406h-web")["active"] is True
            with client.websocket_connect("/ws") as esp:
                welcome = _hello(esp, "esp32")
                assert welcome["active"] is True
                notice = rg.receive_json()
                assert notice == {"type": "active_body", "active_body": "esp32", "active": False}
            # ESP32 left: the RG406H is the Active Body again.
            assert rg.receive_json() == {"type": "active_body", "active_body": "rg406h-web", "active": True}


def test_plain_browser_does_not_steal_lupin_from_rg406h(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as rg, client.websocket_connect("/ws") as mac:
            _hello(rg, "rg406h-web")
            welcome = _hello(mac, "web")
            assert welcome["active"] is False and welcome["active_body"] == "rg406h-web"


def test_same_type_the_last_to_arrive_keeps_lupin(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
            _hello(a, "web")
            assert _hello(b, "web")["active"] is True
            assert a.receive_json()["active"] is False


def test_inactive_body_does_not_receive_the_voice(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        return b"x"

    with TestClient(_app(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=True)
            assert _hello(rg, "rg406h-web", audio=True)["active"] is False
            events = _turn(rg)
    assert "done" in [e["type"] for e in events]
    assert not [e for e in events if e["type"] == "audio"]
