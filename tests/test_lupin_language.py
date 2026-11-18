"""Lupin's language setting (issue 15): pt-BR (default) or English, saved on the Brain."""

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

from app import speech
from app.config import Settings
from app.llm import LLMClient, build_system_prompt
from app.main import create_app
from app.memory import MemoryStore
from app.skills import build_skills_prompt, list_skills_payload
from app.stt import LocalSTT
from app.today import compose_first_wake_speech
from app.tts import ServerTTS

MAC_IP = "192.168.0.10"
OTHER_IP = "192.168.0.77"
TODAY = "2026-11-17"
STATE = {
    "workspace_exists": True,
    "tasks": [
        {"id": "t-1", "title": "Review the intro", "status": "open", "due": TODAY},
        {"id": "t-2", "title": "Reply to advisor", "status": "open"},
    ],
}
CALENDAR = [
    {"start": "09:00", "title": "Lab meeting", "all_day": False},
    {"start": "14:30", "title": "Dentist", "all_day": False},
]


def _as_client(app: Any, host: str) -> Any:
    async def asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        patched = dict(scope)
        patched["client"] = (host, 54321)
        await app(patched, receive, send)

    return asgi


def _app(tmp_path: Path, **extra: Any) -> Any:
    settings = Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
        desk_dev_no_token=True,
    )
    return create_app(settings=settings, local_ips=lambda: frozenset({MAC_IP}), **extra)


# ---------------------------------------------------------------------------
# First Wake and the prompt, in both languages
# ---------------------------------------------------------------------------


def test_first_wake_in_portuguese_by_default() -> None:
    text = " ".join(compose_first_wake_speech(STATE, CALENDAR, TODAY))
    assert "Bom dia!" in text and "2 tarefas abertas" in text
    assert "9h00 Lab meeting" in text


def test_first_wake_in_english() -> None:
    speech.set_language("en")
    sentences = compose_first_wake_speech(STATE, CALENDAR, TODAY)
    text = " ".join(sentences)
    assert 2 <= len(sentences) <= 3
    assert "Good morning!" in text and "2 open tasks" in text
    assert "9:00 AM Lab meeting" in text and "2:30 PM Dentist" in text
    assert "Review the intro, which is due today" in text
    assert "Bom dia" not in text and "tarefas" not in text


def test_first_wake_english_when_calendar_free_or_workspace_missing() -> None:
    speech.set_language("en")
    assert any("calendar is clear" in s for s in compose_first_wake_speech(STATE, [], TODAY))
    sentences = compose_first_wake_speech({"workspace_exists": False}, None, TODAY)
    assert "couldn't read Cowork" in sentences[0]


def test_system_prompt_asks_for_the_chosen_language() -> None:
    assert "português do Brasil" in build_system_prompt()
    speech.set_language("en")
    prompt = build_system_prompt(temporal_context=speech.temporal_context_line("morning", "08:00", "1 hour ago"))
    assert "Always answer in English" in prompt
    assert "português" not in prompt
    assert "[emotion:<name>]" in prompt and "[action:today:brief]" in prompt


def test_skills_follow_the_language() -> None:
    speech.set_language("en")
    prompt = build_skills_prompt(["focus_coach"])
    assert "Focus Coach skill is on" in prompt
    hint = list_skills_payload(["focus_coach"])["packs"][0]["voice_hint"]
    assert "pomodoro" in hint and "bora" not in hint


def test_english_module_exposes_every_public_name_of_the_portuguese_one() -> None:
    from app import speech_en, speech_pt_br

    public = {n for n in vars(speech_pt_br) if not n.startswith("_")}
    assert public <= {n for n in vars(speech_en) if not n.startswith("_")}


# ---------------------------------------------------------------------------
# The setting
# ---------------------------------------------------------------------------


def test_default_is_pt_br(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        data = client.get("/api/lupin-language").json()
    assert data["language"] == "pt-BR"
    assert data["languages"] == ["pt-BR", "en"]
    assert data["tts_voice"] == "Luciana" and data["stt_language"] == "pt"
    assert "Pomodoro" in data["phrases"]["pomodoro_focus_done"]


def test_changing_from_a_non_mac_client_works(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as mac:
        other = TestClient(_as_client(app, OTHER_IP))
        res = other.put("/api/lupin-language", json={"language": "en"})
        assert res.status_code == 200
        assert res.json()["language"] == "en"
        # Every Body sees the same value.
        assert mac.get("/api/lupin-language").json()["language"] == "en"
        assert other.get("/api/lupin-language").json()["language"] == "en"


def test_unsupported_language_is_rejected(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        assert client.put("/api/lupin-language", json={"language": "fr"}).status_code == 422
        assert client.get("/api/lupin-language").json()["language"] == "pt-BR"


def test_setting_persists_across_restarts(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        client.put("/api/lupin-language", json={"language": "en"})
    speech.set_language("pt-BR")  # a fresh process starts in the default
    with TestClient(_app(tmp_path)) as client:
        assert client.get("/api/lupin-language").json()["language"] == "en"
        assert speech.get_language() == "en"
    with TestClient(_app(tmp_path)) as client:
        client.put("/api/lupin-language", json={"language": "pt-BR"})
    with TestClient(_app(tmp_path)) as client:
        assert client.get("/api/lupin-language").json()["language"] == "pt-BR"


# ---------------------------------------------------------------------------
# What follows the setting: STT, TTS voice, the turn's prompt
# ---------------------------------------------------------------------------


def test_stt_receives_the_chosen_language_by_default(tmp_path: Path) -> None:
    seen: list[str] = []

    def fake(audio: bytes, mime: str, lang: str) -> dict[str, Any]:
        seen.append(lang)
        return {"text": "ok", "available": True, "engine": "fake", "error": None}

    payload = {"data": base64.b64encode(b"abc").decode(), "mime_type": "audio/mp4"}
    with TestClient(_app(tmp_path, stt_engine=LocalSTT(transcribe_fn=fake))) as client:
        client.post("/api/stt", json=payload)
        client.put("/api/lupin-language", json={"language": "en"})
        client.post("/api/stt", json=payload)
        client.post("/api/stt", json={**payload, "language": "pt"})  # an explicit client choice wins
    assert seen == ["pt", "en", "pt"]


def test_tts_voice_follows_the_language(tmp_path: Path) -> None:
    voices: list[str] = []

    def synth(text: str, voice: str, fmt: str) -> tuple[bytes, str]:
        voices.append(voice)
        return b"x", "audio/mp4"

    with TestClient(_app(tmp_path, tts_engine=ServerTTS(synth_fn=synth))) as client:
        client.post("/api/tts", json={"text": "oi"})
        client.put("/api/lupin-language", json={"language": "en"})
        client.post("/api/tts", json={"text": "hi"})
        client.post("/api/tts", json={"text": "hi", "voice": "Daniel"})
        data = client.get("/api/tts/voices").json()
    assert voices == ["Luciana", "Samantha", "Daniel"]
    assert data["default_voice"] == "Samantha"


def test_next_turn_uses_english_and_nothing_is_replayed(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    settings = Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
        desk_dev_no_token=True,
    )

    async def fake_stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        calls.append(kwargs)
        yield {"type": "result", "text": "Hi!", "raw_text": "Hi!", "emotion": "neutral"}

    memory = MemoryStore(db_path=settings.db_path)
    from app.today import FirstWakeTracker

    app = create_app(
        settings=settings,
        memory_store=memory,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        first_wake=FirstWakeTracker(memory, clock=lambda: datetime(2026, 11, 17, 3, 0)),
        calendar_reader=lambda: None,
        inbox_reader=lambda: None,
    )
    with TestClient(app) as client:
        client.put("/api/lupin-language", json={"language": "en"})
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
            ws.receive_json()
            ws.send_json({"type": "text", "text": "hello"})
            while ws.receive_json()["type"] != "done":
                pass
    assert len(calls) == 1
    assert "Last interaction" in calls[0]["temporal_context"]
    assert "Pet state: mood" in calls[0]["companion_context"]
    assert "You do NOT have access to the user's calendar" in calls[0]["personal_context"]
