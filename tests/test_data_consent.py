"""Data Consent tests (issue 03): calendar and e-mail only reach the LLM with consent."""

from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.consent import DataConsent, build_personal_context
from app.llm import LLMClient, build_system_prompt
from app.main import create_app
from app.memory import MemoryStore

MAC_IP = "192.168.1.10"
OTHER_IP = "192.168.1.50"
CALENDAR = [{"start": "09:00", "title": "Defesa do Zeca", "all_day": False}]
INBOX = {
    "unread": 7,
    "recent": [{"sender": "Carla Souza", "subject": "Contrato assinado"}],
}
SECRETS = ("Defesa do Zeca", "Carla Souza", "Contrato assinado")


def _as_client(app: Any, host: str) -> Any:
    async def asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        patched = dict(scope)
        patched["client"] = (host, 54321)
        await app(patched, receive, send)

    return asgi


def _app(tmp_path: Path, calls: list[dict[str, Any]], calendar: Any = CALENDAR, inbox: Any = INBOX) -> Any:
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
        yield {"type": "sentence", "text": "Oi!"}
        yield {"type": "result", "text": "Oi!", "raw_text": "Oi!", "emotion": "neutral"}

    return create_app(
        settings=settings,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        calendar_reader=lambda: calendar,
        inbox_reader=lambda: inbox,
        local_ips=lambda: frozenset({MAC_IP}),
    )


def _until_reply(ws: Any) -> None:
    """Wait for the turn reply's `done` (ignoring the First Wake one, if any)."""
    while True:
        ev = ws.receive_json()
        if ev["type"] == "done" and not ev.get("first_wake"):
            return


def _conversation(client: Any, text: str = "o que tenho hoje?") -> None:
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        ws.receive_json()
        ws.send_json({"type": "text", "text": text})
        _until_reply(ws)


def test_default_off_and_named_receiver(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    with TestClient(app, base_url="http://localhost") as mac:
        data = mac.get("/api/data-consent").json()
    assert data["calendar"] is False and data["email"] is False
    assert data["receiver"] == "Proxy Local (127.0.0.1:31415)"
    assert data["can_edit"] is True
    assert "test-key" not in repr(data)


def test_without_consent_no_calendar_or_email_reaches_the_llm(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    with TestClient(_app(tmp_path, calls), base_url="http://localhost") as client:
        _conversation(client)
    assert len(calls) == 1
    for secret in SECRETS:
        assert secret not in repr(calls[0])
    ctx = calls[0]["personal_context"]
    assert "NÃO tem acesso à agenda" in ctx and "NÃO tem acesso aos e-mails" in ctx


def test_with_consent_calendar_and_email_reach_the_llm(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    app = _app(tmp_path, calls)
    with TestClient(app, base_url="http://localhost") as mac:
        assert mac.put("/api/data-consent", json={"calendar": True, "email": True}).status_code == 200
        _conversation(mac)
    ctx = calls[0]["personal_context"]
    assert "09:00 Defesa do Zeca" in ctx
    assert "Carla Souza" in ctx and "Contrato assinado" in ctx


def test_calendar_only_consent_does_not_leak_email(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    app = _app(tmp_path, calls)
    with TestClient(app, base_url="http://localhost") as mac:
        mac.put("/api/data-consent", json={"calendar": True})
        _conversation(mac)
    ctx = calls[0]["personal_context"]
    assert "Defesa do Zeca" in ctx
    assert "Carla Souza" not in repr(calls[0]) and "Contrato assinado" not in repr(calls[0])


def test_failed_read_with_consent_warns_without_data(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    app = _app(tmp_path, calls, calendar=None, inbox=None)
    with TestClient(app, base_url="http://localhost") as mac:
        mac.put("/api/data-consent", json={"calendar": True, "email": True})
        _conversation(mac)
    ctx = calls[0]["personal_context"]
    assert "não conseguiu ler a agenda" in ctx and "não conseguiu ler os e-mails" in ctx


def test_calendar_and_email_do_not_go_into_the_saved_history(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    app = _app(tmp_path, calls)
    with TestClient(app, base_url="http://localhost") as mac:
        mac.put("/api/data-consent", json={"calendar": True, "email": True})
        with mac.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
            ws.receive_json()
            ws.send_json({"type": "text", "text": "o que tenho hoje?"})
            _until_reply(ws)
        salvo = repr(app.state.memory.get_recent_messages()) + repr(app.state.memory.get_facts())
    for secret in SECRETS:
        assert secret not in salvo


def test_changing_from_outside_the_mac_gives_403_and_reading_still_works(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    with TestClient(app, base_url="http://localhost") as mac:
        mac.put("/api/data-consent", json={"calendar": True})
        other = TestClient(_as_client(app, OTHER_IP))
        assert other.put("/api/data-consent", json={"calendar": False}).status_code == 403
        assert other.put("/api/data-consent", json={"email": True}).status_code == 403
        read_back = other.get("/api/data-consent").json()
        assert read_back["calendar"] is True and read_back["email"] is False and read_back["can_edit"] is False
        assert mac.get("/api/data-consent").json()["calendar"] is True


def test_switching_provider_or_base_url_turns_both_off(tmp_path: Path) -> None:
    app = _app(tmp_path, [])
    body = {"provider_id": "local_proxy", "base_url": "http://127.0.0.1:31415/v1", "model": "m"}
    with TestClient(app, base_url="http://localhost") as mac:
        mac.put("/api/data-consent", json={"calendar": True, "email": True})
        # Same provider and host: stays on.
        mac.put("/api/llm/provider", json=body)
        assert mac.get("/api/data-consent").json()["calendar"] is True
        # Another host, same provider (custom).
        mac.put("/api/llm/provider", json={**body, "provider_id": "custom", "base_url": "http://10.0.0.5:1/v1"})
        data = mac.get("/api/data-consent").json()
        assert data["calendar"] is False and data["email"] is False
        # Going back to the local proxy does not re-enable it on its own.
        mac.put("/api/llm/provider", json=body)
        assert mac.get("/api/data-consent").json()["calendar"] is False
        # Turn it on again, switch only the provider (Ollama): turns off.
        mac.put("/api/data-consent", json={"calendar": True, "email": True})
        mac.put("/api/llm/provider", json={"provider_id": "ollama", "base_url": "http://192.168.1.20:11434/v1", "model": "llama3.2"})
        data = mac.get("/api/data-consent").json()
        assert data["calendar"] is False and data["email"] is False
        assert data["receiver"].startswith("Ollama")
        # Changing only the base_url of the same provider also turns it off.
        mac.put("/api/data-consent", json={"calendar": True})
        mac.put("/api/llm/provider", json={"provider_id": "ollama", "base_url": "http://192.168.1.20:9999/v1", "model": "llama3.2"})
        assert mac.get("/api/data-consent").json()["calendar"] is False


def test_signature_in_the_class(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    try:
        sig = [("ollama", "http://192.168.1.20:11434/v1")]
        consent = DataConsent(mem, lambda: sig[0])
        consent.update(calendar=True, email=True)
        assert consent.get() == {"calendar": True, "email": True}
        sig[0] = ("ollama", "http://192.168.1.20:11435/v1")
        assert consent.get() == {"calendar": False, "email": False}
        sig[0] = ("ollama", "http://192.168.1.20:11434/v1")
        assert consent.get() == {"calendar": False, "email": False}, "going back does not re-enable"
    finally:
        mem.close()


def test_personal_context_and_prompt() -> None:
    off = build_personal_context({"calendar": False, "email": False}, CALENDAR, INBOX)
    assert not any(s in off for s in SECRETS)
    on = build_personal_context({"calendar": True, "email": True}, CALENDAR, INBOX)
    assert "Defesa do Zeca" in on and "Contrato assinado" in on
    assert "corpo" in on  # reminds that it only sees sender and subject
    assert "Defesa do Zeca" in build_system_prompt(personal_context=on)
    assert "Agenda e e-mails" not in build_system_prompt()


def test_old_stored_format_with_agenda_key_is_still_read(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    try:
        sig = ("ollama", "http://192.168.1.20:11434/v1")
        mem.set_meta(
            "data_consent",
            json.dumps({"agenda": True, "email": False, "provider_id": sig[0], "host": "192.168.1.20:11434"}),
        )
        consent = DataConsent(mem, lambda: sig)
        assert consent.get() == {"calendar": True, "email": False}
        # The value is rewritten under the new key.
        stored = json.loads(mem.get_meta("data_consent") or "{}")
        assert stored["calendar"] is True and "agenda" not in stored
    finally:
        mem.close()
