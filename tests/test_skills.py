"""Tests for the Pet Skills system (modular packs, interactive tricks and WebSocket)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LLMClient, build_system_prompt
from app.main import create_app


def _build_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="claude-haiku-4-5",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
    )


def test_skills_api_and_persistence_across_restarts(tmp_path: Path) -> None:
    app1 = create_app(settings=_build_settings(tmp_path))
    with TestClient(app1) as client:
        res = client.get("/api/skills")
        assert res.status_code == 200
        data = res.json()
        assert len(data["packs"]) == 5
        assert len(data["tricks"]) == 6
        assert "wellness_breaks" not in data["enabled_ids"]

        toggle_on = client.put("/api/skills/wellness_breaks", json={"enabled": True})
        assert toggle_on.status_code == 200
        assert "wellness_breaks" in toggle_on.json()["enabled_ids"]

        toggle_off = client.put("/api/skills/focus_coach", json={"enabled": False})
        assert toggle_off.status_code == 200
        assert "focus_coach" not in toggle_off.json()["enabled_ids"]

        unknown_skill = client.put("/api/skills/nonexistent", json={"enabled": True})
        assert unknown_skill.status_code == 404

        trick_ok = client.post("/api/skills/tricks/dance")
        assert trick_ok.status_code == 200
        assert trick_ok.json()["trick"]["id"] == "dance"

        trick_404 = client.post("/api/skills/tricks/backflip")
        assert trick_404.status_code == 404

    # A new instance on the same SQLite preserves the choices
    app2 = create_app(settings=_build_settings(tmp_path))
    with TestClient(app2) as client2:
        data2 = client2.get("/api/skills").json()
        assert "wellness_breaks" in data2["enabled_ids"]
        assert "focus_coach" not in data2["enabled_ids"]


def test_build_system_prompt_injects_skills_context() -> None:
    prompt = build_system_prompt(skills_context="- Skill Bem-Estar & Pausas ativa")
    assert "Skills e truques do pet habilitados:" in prompt
    assert "Skill Bem-Estar & Pausas ativa" in prompt


def test_websocket_pet_trick_action_emits_action_executed(tmp_path: Path) -> None:
    captured_kwargs: dict[str, Any] = {}

    async def fake_stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        captured_kwargs.update(kwargs)
        yield {"type": "emotion", "emotion": "excited"}
        yield {"type": "action", "kind": "pet", "target": "dance"}
        yield {"type": "delta", "text": "Olha minha dancinha!"}
        yield {"type": "sentence", "text": "Olha minha dancinha!"}
        yield {
            "type": "result",
            "clean_text": "Olha minha dancinha!",
            "raw_text": "[emotion:excited] [action:pet:dance] Olha minha dancinha!",
            "emotion": "excited",
            "facts": [],
        }

    settings = _build_settings(tmp_path)
    llm_client = LLMClient(settings=settings, stream_fn=fake_stream)
    app = create_app(settings=settings, llm_client=llm_client)

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "faz uma dancinha"})

            events: list[dict[str, Any]] = []
            for _ in range(15):
                ev = ws.receive_json()
                events.append(ev)
                if ev.get("type") == "done":
                    break

            action_events = [
                e for e in events if e.get("type") == "action_executed" and e.get("kind") == "pet"
            ]
            assert len(action_events) == 1
            assert action_events[0]["ok"] is True
            assert action_events[0]["target"] == "dance"
            assert "skills_context" in captured_kwargs
            assert "Truques físicos disponíveis" in captured_kwargs["skills_context"]
