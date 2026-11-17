"""First Wake tests (issue 03): the Today summary spoken in Lupin's voice on the Active Body."""

from __future__ import annotations

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
from app.mac_control import parse_calendar_output
from app.main import create_app
from app.memory import MemoryStore
from app.today import FirstWakeTracker, compose_first_wake_speech
from app.tts import ServerTTS

TODAY = "2026-11-17"
STATE = {
    "workspace_exists": True,
    "tasks": [
        {"id": "t-1", "title": "Revisar a introdução", "status": "open", "due": TODAY},
        {"id": "t-2", "title": "Responder orientador", "status": "open"},
        {"id": "t-3", "title": "Tarefa fechada", "status": "done"},
    ],
}
CALENDAR = [
    {"start": "09:00", "title": "Reunião de laboratório", "all_day": False},
    {"start": "14:30", "title": "Dentista", "all_day": False},
]


def test_speech_has_tasks_calendar_and_priority_in_three_sentences() -> None:
    sentences = compose_first_wake_speech(STATE, CALENDAR, TODAY)
    assert len(sentences) == 3
    text = " ".join(sentences)
    assert "2 tarefas abertas" in text
    assert "9h00 Reunião de laboratório" in text and "14h30 Dentista" in text
    assert "Revisar a introdução" in text  # due today, comes first
    assert "Tarefa fechada" not in text


def test_calendar_empty_or_unavailable() -> None:
    free_calendar = compose_first_wake_speech(STATE, [], TODAY)
    assert any("agenda está livre" in f for f in free_calendar)
    unavailable = compose_first_wake_speech(STATE, None, TODAY)
    assert not any("agenda" in f.lower() for f in unavailable)
    assert 2 <= len(unavailable) <= 3


def test_without_cowork_and_calendar_still_speaks_two_sentences_without_inventing() -> None:
    sentences = compose_first_wake_speech({"workspace_exists": False}, None, TODAY)
    assert 2 <= len(sentences) <= 3
    assert not any(ch.isdigit() for ch in " ".join(sentences))


def test_long_calendar_is_summarized_in_three_items() -> None:
    many = [{"start": f"{h:02d}:00", "title": f"Evento {h}", "all_day": False} for h in range(8, 14)]
    sentence = [f for f in compose_first_wake_speech(STATE, many, TODAY) if "agenda" in f.lower()][0]
    assert "Evento 10" in sentence and "Evento 11" not in sentence and "mais 3" in sentence


def test_all_day_appears_without_hour() -> None:
    sentences = compose_first_wake_speech(STATE, [{"start": "00:00", "title": "Feriado", "all_day": True}], TODAY)
    assert any("Feriado (dia todo)" in f for f in sentences)


def test_tracker_only_triggers_after_5am_and_once_per_day(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    try:
        clock = [datetime(2026, 11, 17, 4, 59)]
        tracker = FirstWakeTracker(mem, clock=lambda: clock[0])
        assert tracker.is_due() is False
        clock[0] = datetime(2026, 11, 17, 5, 0)
        assert tracker.is_due() is True
        tracker.mark_triggered()
        assert tracker.is_due() is False
        clock[0] = datetime(2026, 11, 18, 6, 0)
        assert tracker.is_due() is True
    finally:
        mem.close()


def test_parses_calendar_app_output() -> None:
    output = "32400\tfalse\tReunião\n0\ttrue\tFeriado\n52200\tfalse\tDentista\tcom tab\n\nlixo\n"
    assert parse_calendar_output(output) == [
        {"start": "00:00", "title": "Feriado", "all_day": True},
        {"start": "09:00", "title": "Reunião", "all_day": False},
        {"start": "14:30", "title": "Dentista com tab", "all_day": False},
    ]


# ---------------------------------------------------------------------------
# Over the WebSocket
# ---------------------------------------------------------------------------


INBOX = {
    "unread": 2,
    "recent": [
        {"sender": "Carla Souza", "subject": "Contrato assinado"},
        {"sender": "Banco", "subject": "Fatura aberta"},
    ],
}


def _app(
    tmp_path: Path,
    hour: int,
    llm_calls: list[dict[str, Any]],
    inbox: dict[str, Any] | None = None,
) -> tuple[Any, list[str]]:
    settings = Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
    )
    synthesized: list[str] = []

    async def fake_stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        llm_calls.append(kwargs)
        yield {"type": "sentence", "text": "Oi!"}
        yield {"type": "result", "text": "Oi!", "raw_text": "Oi!", "emotion": "neutral"}

    async def synth(text: str, voice: str, fmt: str) -> bytes:
        synthesized.append(text)
        return b"x"

    memory = MemoryStore(db_path=settings.db_path)
    tracker = FirstWakeTracker(memory, clock=lambda: datetime(2026, 11, 17, hour, 10))
    app = create_app(
        settings=settings,
        memory_store=memory,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        tts_engine=ServerTTS(synth_fn=synth),
        first_wake=tracker,
        calendar_reader=lambda: list(CALENDAR),
        inbox_reader=lambda: inbox,
    )
    return app, synthesized


def _until_done(ws: Any) -> list[dict[str, Any]]:
    events = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] == "done":
            return events


def test_first_touch_after_5am_speaks_today_with_voice(tmp_path: Path) -> None:
    app, synthesized = _app(tmp_path, 7, [])
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1, "audio": ["m4a"]})
        ws.receive_json()
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        events = _until_done(ws)
        sentences = [e["text"] for e in events if e["type"] == "sentence"]
        assert 2 <= len(sentences) <= 3
        assert events[-1]["first_wake"] is True
        # The voice of each sentence arrives after the done.
        audios = []
        while len(audios) < len(sentences):
            ev = ws.receive_json()
            if ev["type"] == "audio" and ev["last"]:
                audios.append(ev)
        assert synthesized == sentences

        # Second touch on the same day: mood only.
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        ws.send_json({"type": "typing", "active": False})
        assert ws.receive_json() == {"type": "state", "state": "idle"}


def test_no_first_wake_before_5am(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, 3, [])
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        ws.send_json({"type": "typing", "active": False})
        assert ws.receive_json() == {"type": "state", "state": "idle"}


def test_body_that_is_not_the_active_body_does_not_trigger(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, 7, [])
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as esp, client.websocket_connect("/ws") as rg:
            esp.send_json({"type": "hello", "body": "esp32", "protocol": 1})
            esp.receive_json()
            rg.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
            assert rg.receive_json()["active"] is False
            rg.send_json({"type": "touch", "kind": "pet"})
            assert rg.receive_json()["type"] == "mood"
            rg.send_json({"type": "typing", "active": False})
            assert rg.receive_json() == {"type": "state", "state": "idle"}
            # The First Wake stays reserved for the Active Body.
            esp.send_json({"type": "touch", "kind": "pet"})
            assert esp.receive_json()["type"] == "mood"
            assert _until_done(esp)[-1]["first_wake"] is True


def test_text_gets_first_wake_first_and_calendar_does_not_reach_the_llm(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    app, _ = _app(tmp_path, 7, calls)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "text", "text": "bom dia"})
        first = _until_done(ws)
        assert first[-1]["first_wake"] is True
        second = _until_done(ws)
        assert second[-1].get("first_wake") is not True
        assert second[-1]["text"] == "Oi!"
    assert len(calls) == 1
    assert "Dentista" not in repr(calls[0])
    assert "Reunião de laboratório" not in repr(calls[0])


# ---------------------------------------------------------------------------
# Inbox (Mail.app) in the First Wake
# ---------------------------------------------------------------------------

from app.mac_control import parse_mail_output  # noqa: E402


def test_parses_mail_app_output() -> None:
    output = "12\nAna <ana@x.com>\tOrçamento\nBob\tRe: reunião\tcom tab\n\nlixo\n"
    assert parse_mail_output(output) == {
        "unread": 12,
        "recent": [
            {"sender": "Ana <ana@x.com>", "subject": "Orçamento"},
            {"sender": "Bob", "subject": "Re: reunião com tab"},
        ],
    }
    assert parse_mail_output("0\n") == {"unread": 0, "recent": []}
    assert parse_mail_output("") is None
    assert parse_mail_output("erro\n") is None
    many = "3\n" + "".join(f"R{i}\tA{i}\n" for i in range(15))
    assert len(parse_mail_output(many)["recent"]) == 10


def test_first_wake_speaks_the_unread_count() -> None:
    sentences = compose_first_wake_speech(STATE, CALENDAR, TODAY, 12)
    assert len(sentences) <= 3
    assert sentences[0] == "Bom dia! Você tem 2 tarefas abertas e 12 e-mails não lidos."


def test_first_wake_singular_zero_and_without_cowork() -> None:
    one = {"workspace_exists": True, "tasks": [{"title": "A", "status": "open"}]}
    assert compose_first_wake_speech(one, None, TODAY, 1)[0] == "Bom dia! Você tem 1 tarefa aberta e 1 e-mail não lido."
    assert compose_first_wake_speech(one, None, TODAY, 0)[0] == "Bom dia! Você tem 1 tarefa aberta e nenhum e-mail não lido."
    empty_state = {"workspace_exists": True, "tasks": []}
    assert compose_first_wake_speech(empty_state, None, TODAY, 3)[0] == "Bom dia! Nenhuma tarefa aberta e 3 e-mails não lidos."
    unavailable = compose_first_wake_speech({"workspace_exists": False}, None, TODAY, 5)
    assert unavailable[0] == "Bom dia! Não consegui ler o Cowork agora, mas você tem 5 e-mails não lidos."
    assert len(unavailable) <= 3


def test_first_wake_without_mail_read_stays_as_before() -> None:
    assert compose_first_wake_speech(STATE, CALENDAR, TODAY) == compose_first_wake_speech(STATE, CALENDAR, TODAY, None)
    assert not any("e-mail" in f for f in compose_first_wake_speech(STATE, CALENDAR, TODAY, None))


def test_first_wake_over_ws_speaks_count_without_sender_or_subject(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    app, _ = _app(tmp_path, 7, calls, inbox=INBOX)
    with TestClient(app) as client, client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "touch", "kind": "pet"})
        assert ws.receive_json()["type"] == "mood"
        text = " ".join(e["text"] for e in _until_done(ws) if e["type"] == "sentence")
    assert "2 e-mails não lidos" in text
    assert "Carla" not in text and "Contrato" not in text
    assert calls == []
