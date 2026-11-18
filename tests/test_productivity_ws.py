"""End to end: a voice turn records a task and Lupin confirms it (needs the 05 main.py patch)."""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.config import Settings
from app.llm import LLMClient
from app.main import create_app
from app.memory import MemoryStore


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_base_url="http://127.0.0.1:31415/v1",
        llm_api_key="test-key",
        llm_model="m",
        host="127.0.0.1",
        port=8000,
        max_short_term_messages=10,
        max_user_facts=25,
        db_path=tmp_path / "m.db",
    )


def test_voice_task_add_is_stored_and_confirmed(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    memory = MemoryStore(db_path=settings.db_path)

    async def stream(**_kwargs):
        yield {"type": "emotion", "emotion": "happy"}
        yield {"type": "action", "kind": "task", "target": "add:buy milk"}
        yield {"type": "result", "text": "", "raw_text": "", "emotion": "happy"}

    app = create_app(settings=settings, memory_store=memory, llm_client=LLMClient(settings))
    app.state.llm._stream_fn = stream
    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "add a task"})
            events = []
            while True:
                ev = ws.receive_json()
                events.append(ev)
                if ev["type"] == "memory_updated":
                    break
        assert any(e["type"] == "action_executed" and e["kind"] == "task" and e["ok"] for e in events)
        assert any(e["type"] == "sentence" and "buy milk" in e["text"] for e in events)
        tasks = client.get("/api/tasks").json()["tasks"]
        assert [t["title"] for t in tasks] == ["buy milk"]
    memory.close()
