"""Tests for issue 09 (Dock): the Mac as the only Shortcuts editor and replies on the Active Body."""

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

MAC_IP = "192.168.1.10"
OTHER_IP = "192.168.1.50"


def _settings(tmp_path: Path, **extra: Any) -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
        **extra,
    )


def _as_client(app: Any, host: str) -> Any:
    async def asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        patched = dict(scope)
        patched["client"] = (host, 54321)
        await app(patched, receive, send)

    return asgi


def _app_shortcuts(tmp_path: Path) -> Any:
    settings = _settings(tmp_path, desk_dev_no_token=True)
    return create_app(settings=settings, local_ips=lambda: frozenset({MAC_IP}))


NEW_SHORTCUT = {"title": "Abrir Notas", "action_type": "app_activate", "payload": {"app": "Notes"}}


def test_client_info_says_whether_the_client_is_the_mac(tmp_path: Path) -> None:
    app = _app_shortcuts(tmp_path)
    with TestClient(app) as local:
        assert local.get("/api/client-info").json() == {"is_mac": True}
    with TestClient(_as_client(app, MAC_IP)) as mac_over_lan:
        assert mac_over_lan.get("/api/client-info").json() == {"is_mac": True}
    with TestClient(_as_client(app, OTHER_IP)) as other:
        assert other.get("/api/client-info").json() == {"is_mac": False}


def test_shortcut_writes_only_on_the_mac_even_without_token(tmp_path: Path) -> None:
    app = _app_shortcuts(tmp_path)
    # Only the first client runs the lifespan (and closes SQLite at the end).
    with TestClient(app) as mac:
        created = mac.post("/api/shortcuts", json=NEW_SHORTCUT)
        assert created.status_code == 201
        sid = created.json()["id"]

        other = TestClient(_as_client(app, OTHER_IP))
        # Reading stays open (dev without token); writing does not.
        assert other.get("/api/shortcuts").status_code == 200
        assert other.post("/api/shortcuts", json=NEW_SHORTCUT).status_code == 403
        assert other.put(f"/api/shortcuts/{sid}", json={"title": "x"}).status_code == 403
        assert other.put(f"/api/shortcuts/{sid}", json={"pinned_on_deck": True}).status_code == 403
        assert other.delete(f"/api/shortcuts/{sid}").status_code == 403
        assert other.post("/api/shortcuts/reorder", json={"ordered_ids": [sid]}).status_code == 403
        assert other.post("/api/shortcuts/reset-defaults").status_code == 403

        mac_lan = TestClient(_as_client(app, MAC_IP))
        assert mac_lan.put(f"/api/shortcuts/{sid}", json={"title": "Notas"}).status_code == 200
        assert mac_lan.delete(f"/api/shortcuts/{sid}").status_code == 200


def test_new_shortcut_starts_unpinned(tmp_path: Path) -> None:
    app = _app_shortcuts(tmp_path)
    with TestClient(app) as mac:
        created = mac.post("/api/shortcuts", json=NEW_SHORTCUT).json()
        assert created["pinned_on_deck"] is False
        pinned = mac.put(f"/api/shortcuts/{created['id']}", json={"pinned_on_deck": True}).json()
        assert pinned["pinned_on_deck"] is True
    store = ShortcutStore(db_path=tmp_path / "direct.db")
    try:
        assert store.create_shortcut(NEW_SHORTCUT)["pinned_on_deck"] is False
    finally:
        store.close()


# ---------------------------------------------------------------------------
# Routing the reply to the Active Body
# ---------------------------------------------------------------------------


def _app_ws(tmp_path: Path, synth: Any, *, hour: int = 3, stt: Any = None) -> Any:
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
        first_wake=FirstWakeTracker(memory, clock=lambda: datetime(2026, 11, 17, hour, 0)),
        calendar_reader=lambda: [],
    )


def _hello(ws: Any, body: str, audio: bool = False) -> dict[str, Any]:
    ws.send_json({"type": "hello", "body": body, "protocol": 1, "audio": ["m4a"] if audio else []})
    return ws.receive_json()


def _until(ws: Any, kind: str) -> list[dict[str, Any]]:
    events = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] == kind:
            return events


async def _synth_ok(text: str, voice: str, fmt: str) -> bytes:
    return b"voice:" + text.encode()


def _audios_until_last(ws: Any, sentences: int) -> list[dict[str, Any]]:
    audios: list[dict[str, Any]] = []
    while len([a for a in audios if a["last"]]) < sentences:
        ev = ws.receive_json()
        assert ev["type"] == "audio", ev
        audios.append(ev)
    return audios


def test_inactive_asker_gets_text_and_voice_goes_to_the_active_body(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=True)
            assert _hello(rg, "rg406h-web", audio=True)["active"] is False
            rg.send_json({"type": "text", "text": "oi"})

            # The asker: text only, no audio and no from_body.
            events_rg = _until(rg, "memory_updated")
            kinds = [e["type"] for e in events_rg]
            assert kinds[0] == "state"
            assert [e["text"] for e in events_rg if e["type"] == "sentence"] == ["Oi!", "Tudo bem?"]
            assert "done" in kinds and "audio" not in kinds
            assert not any("from_body" in e for e in events_rg)

            # Active Body: expression, sentences, done and voice, all with from_body.
            events_esp = _until(esp, "done")
            assert [e["type"] for e in events_esp] == ["emotion", "sentence", "sentence", "done"]
            assert all(e["from_body"] == "rg406h-web" for e in events_esp)
            assert events_esp[0]["emotion"] == "happy"
            assert events_esp[-1]["text"] == "Oi! Tudo bem?"
            audios = _audios_until_last(esp, 2)
            assert all(a["from_body"] == "rg406h-web" for a in audios)
            voice = {
                a["sentence"]: base64.b64decode(a["data"]) for a in audios if a["last"]
            }
            assert voice == {0: b"voice:Oi!", 1: b"voice:Tudo bem?"}


def test_audio_question_from_the_inactive_body_is_also_mirrored(tmp_path: Path) -> None:
    class _Stt:
        async def transcribe_bytes(self, **kwargs: Any) -> dict[str, Any]:
            return {"text": "oi", "engine": "fake"}

    app = _app_ws(tmp_path, _synth_ok, stt=_Stt())
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=True)
            _hello(rg, "rg406h-web", audio=True)
            rg.send_json({"type": "audio", "data": base64.b64encode(b"abc").decode(), "mime_type": "audio/webm"})
            events_rg = _until(rg, "memory_updated")
            assert "transcript" in [e["type"] for e in events_rg]
            assert not [e for e in events_rg if e["type"] == "audio"]
            events_esp = _until(esp, "done")
            assert all(e["from_body"] == "rg406h-web" for e in events_esp)
            assert "transcript" not in [e["type"] for e in events_esp]


def test_active_body_without_declared_audio_receives_text_only(tmp_path: Path) -> None:
    async def synth(text: str, voice: str, fmt: str) -> bytes:
        raise AssertionError("TTS should not be called")

    with TestClient(_app_ws(tmp_path, synth)) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=False)
            _hello(rg, "rg406h-web", audio=True)
            rg.send_json({"type": "text", "text": "oi"})
            _until(rg, "memory_updated")
            events_esp = _until(esp, "done")
            assert all(e["from_body"] == "rg406h-web" for e in events_esp)
            esp.send_json({"type": "typing", "active": False})
            assert esp.receive_json() == {"type": "state", "state": "idle"}


def test_when_the_asker_is_the_active_body_nothing_changes(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            _hello(esp, "esp32", audio=True)
            _hello(rg, "rg406h-web", audio=True)
            esp.send_json({"type": "text", "text": "oi"})
            events = _until(esp, "memory_updated")
            assert not any("from_body" in e for e in events)
            _audios_until_last(esp, 2)
            # The Dock receives nothing from the Active Body conversation.
            rg.send_json({"type": "typing", "active": False})
            assert rg.receive_json() == {"type": "state", "state": "idle"}


def test_without_active_body_only_text_returns_to_the_asker(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "text", "text": "oi"})  # no hello: not a Body at all
        events = _until(ws, "memory_updated")
        assert "done" in [e["type"] for e in events]
        assert not [e for e in events if e["type"] in ("audio",)]
        assert not any("from_body" in e for e in events)


def test_active_body_leaving_midway_does_not_break_the_askers_turn(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client:
        with client.websocket_connect("/ws") as rg:
            with client.websocket_connect("/ws") as esp:
                _hello(esp, "esp32", audio=True)
                assert _hello(rg, "rg406h-web", audio=True)["active"] is False
            # ESP32 closed before the question: the RG406H is the Active Body again and nothing breaks.
            assert rg.receive_json() == {"type": "active_body", "active_body": "rg406h-web", "active": True}
            rg.send_json({"type": "text", "text": "oi"})
            events = _until(rg, "memory_updated")
            assert "done" in [e["type"] for e in events]


def test_mirror_to_a_dead_connection_is_ignored(tmp_path: Path) -> None:
    app = _app_ws(tmp_path, _synth_ok)
    with TestClient(app) as client, client.websocket_connect("/ws") as rg:
        _hello(rg, "rg406h-web", audio=True)
        # Simulate an Active Body (esp32) whose connection already dropped but is still registered.
        async def dead(payload: dict[str, Any]) -> None:
            raise RuntimeError("socket closed")

        app.state.bodies.append({"body": "esp32", "seq": 999, "send": dead, "wants_audio": True})
        rg.send_json({"type": "text", "text": "oi"})
        events = _until(rg, "memory_updated")
        assert "done" in [e["type"] for e in events]
        assert "error" not in [e["type"] for e in events]


def test_first_wake_marks_each_sentence(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok, hour=7)) as client, client.websocket_connect("/ws") as ws:
        _hello(ws, "rg406h-web")
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        events = _until(ws, "done")
        sentences = [e for e in events if e["type"] == "sentence"]
        assert len(sentences) >= 2
        assert all(f["first_wake"] is True for f in sentences)
        assert events[-1]["first_wake"] is True


def test_normal_reply_does_not_carry_first_wake(tmp_path: Path) -> None:
    with TestClient(_app_ws(tmp_path, _synth_ok)) as client, client.websocket_connect("/ws") as ws:
        _hello(ws, "rg406h-web")
        ws.send_json({"type": "text", "text": "oi"})
        events = _until(ws, "memory_updated")
        assert not any("first_wake" in e for e in events if e["type"] == "sentence")


@pytest.mark.parametrize("host", ["127.0.0.1", "::1"])
def test_loopback_counts_as_the_mac(tmp_path: Path, host: str) -> None:
    app = _app_shortcuts(tmp_path)
    with TestClient(_as_client(app, host)) as c:
        assert c.get("/api/client-info").json() == {"is_mac": True}
