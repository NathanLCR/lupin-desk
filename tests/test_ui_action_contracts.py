"""REST/WS contracts for sensitive shortcuts and STT interruption."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.shortcuts import ShortcutStore


class _FakeMac:
    def __init__(self) -> None:
        self.shortcuts_run: list[str] = []

    def run_shortcut(self, shortcut: dict[str, Any]) -> dict[str, Any]:
        self.shortcuts_run.append(shortcut["slug"])
        return {"ok": True}

    def list_running_apps(self) -> list[str]:
        return []


class _FakeLLM:
    def __init__(self) -> None:
        self.turns: list[str] = []

    async def stream_chat(self, **kwargs: Any):
        text = str(kwargs["user_text"])
        self.turns.append(text)
        yield {"type": "result", "text": f"Resposta: {text}", "raw_text": "", "emotion": "neutral"}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "ui-contracts.db",
        cowork_workspace_path=tmp_path / "missing-cowork",
        host="127.0.0.1",
    )


def _add_shortcut(
    store: ShortcutStore,
    *,
    slug: str,
    action_type: str = "mac_command",
    payload: dict[str, Any] | None = None,
    requires_confirmation: bool = True,
) -> dict[str, Any]:
    return store.create_shortcut(
        {
            "slug": slug,
            "title": slug.replace("_", " ").title(),
            "action_type": action_type,
            "payload": payload or {"command": "lock_screen"},
            "requires_confirmation": requires_confirmation,
        }
    )


def _receive_until(ws: Any, event_type: str) -> list[dict[str, Any]]:
    events = []
    while True:
        event = ws.receive_json()
        events.append(event)
        if event.get("type") == event_type:
            return events


def test_sensitive_shortcut_rest_conflicts_and_ws_requires_approval(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    shortcuts = ShortcutStore(db_path=settings.db_path)
    _add_shortcut(shortcuts, slug="sensitive_action")
    mac = _FakeMac()
    app = create_app(settings=settings, shortcut_store=shortcuts, mac_controller=mac)  # type: ignore[arg-type]

    with TestClient(app) as client:
        response = client.post("/api/shortcuts/sensitive_action/run")
        assert response.status_code == 409
        assert response.json()["detail"] == {
            "code": "approval_required",
            "message": "This shortcut requires confirmation. Run it over the WebSocket to approve it.",
        }
        assert mac.shortcuts_run == []

        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "run_shortcut", "id": "sensitive_action"})
            request = ws.receive_json()
            assert request["type"] == "tool_approval_request"
            assert request["kind"] == "shortcut"
            assert request["target"] == "sensitive_action"
            assert mac.shortcuts_run == []

            ws.send_json(
                {
                    "type": "confirm_action",
                    "approval_id": request["approval_id"],
                    "approved": False,
                }
            )
            denied = ws.receive_json()
            assert denied["type"] == "action_executed"
            assert denied["cancelled"] is True
            assert mac.shortcuts_run == []

            ws.send_json({"type": "run_shortcut", "id": "sensitive_action"})
            request = ws.receive_json()
            ws.send_json(
                {
                    "type": "confirm_action",
                    "approval_id": request["approval_id"],
                    "approved": True,
                }
            )
            approved = ws.receive_json()
            assert approved["type"] == "action_executed"
            assert approved["ok"] is True
            assert mac.shortcuts_run == ["sensitive_action"]

    shortcuts.close()


def test_confirmed_agent_prompt_starts_turn_and_unconfirmed_still_runs(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    shortcuts = ShortcutStore(db_path=settings.db_path)
    _add_shortcut(
        shortcuts,
        slug="sensitive_prompt",
        action_type="agent_prompt",
        payload={"prompt": "Resuma meu dia"},
    )
    _add_shortcut(
        shortcuts,
        slug="quick_prompt",
        action_type="agent_prompt",
        payload={"prompt": "Diga olá"},
        requires_confirmation=False,
    )
    mac = _FakeMac()
    llm = _FakeLLM()
    app = create_app(
        settings=settings,
        shortcut_store=shortcuts,
        mac_controller=mac,  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "run_shortcut", "id": "sensitive_prompt"})
            approval = ws.receive_json()
            assert approval["type"] == "tool_approval_request"
            assert llm.turns == []
            assert mac.shortcuts_run == []

            ws.send_json(
                {
                    "type": "confirm_action",
                    "approval_id": approval["approval_id"],
                    "approved": True,
                }
            )
            assert ws.receive_json()["type"] == "action_executed"
            events = _receive_until(ws, "memory_updated")
            assert llm.turns == ["Resuma meu dia"]
            assert any(event.get("type") == "done" for event in events)
            assert mac.shortcuts_run == []

            ws.send_json({"type": "run_shortcut", "id": "quick_prompt"})
            events = _receive_until(ws, "memory_updated")
            assert llm.turns == ["Resuma meu dia", "Diga olá"]
            assert any(event.get("type") == "done" for event in events)
            assert mac.shortcuts_run == []

    shortcuts.close()


def test_delayed_stt_does_not_block_receive_loop_or_emit_stale_transcript(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    shortcuts = ShortcutStore(db_path=settings.db_path)
    llm = _FakeLLM()
    mac = _FakeMac()
    cancelled: list[int] = []
    stt_calls = 0

    class _DelayedSTT:
        async def transcribe_bytes(self, **_kwargs: Any) -> dict[str, Any]:
            nonlocal stt_calls
            stt_calls += 1
            call_number = stt_calls
            try:
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                cancelled.append(call_number)
                raise
            return {"text": f"transcrição {call_number}", "engine": "fake"}

    app = create_app(
        settings=settings,
        shortcut_store=shortcuts,
        mac_controller=mac,  # type: ignore[arg-type]
        llm_client=llm,  # type: ignore[arg-type]
        stt_engine=_DelayedSTT(),  # type: ignore[arg-type]
    )
    audio = base64.b64encode(b"audio sintetico").decode("ascii")

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "audio", "data": audio})
            assert ws.receive_json() == {"type": "state", "state": "thinking"}

            ws.send_json({"type": "typing", "active": True})
            assert ws.receive_json() == {"type": "state", "state": "listening"}

            ws.send_json({"type": "interrupt"})
            interrupted = [ws.receive_json(), ws.receive_json()]
            assert {"type": "interrupted"} in interrupted
            assert {"type": "state", "state": "idle"} in interrupted
            assert cancelled == [1]

            ws.send_json({"type": "audio", "data": audio})
            assert ws.receive_json() == {"type": "state", "state": "thinking"}
            ws.send_json({"type": "text", "text": "Nova mensagem"})
            events = _receive_until(ws, "memory_updated")
            assert not any(event.get("type") == "transcript" for event in events)
            assert any(event.get("type") == "done" for event in events)
            assert llm.turns == ["Nova mensagem"]
            assert cancelled == [1, 2]

    shortcuts.close()
