"""Slow local model notice during a chat turn (needs the 11 config and main patches)."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.llm import LLMClient, LLMError
from app.main import create_app

SLOW_AFTER_S = 0.2


def _app(tmp_path: Path, fake_stream: Any) -> Any:
    settings = Settings(
        llm_base_url="http://127.0.0.1:11434/v1",
        llm_api_key="",
        llm_model="llama3.2",
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
        desk_dev_no_token=True,
        local_llm_slow_after_s=SLOW_AFTER_S,
    )
    return create_app(
        settings=settings,
        llm_client=LLMClient(settings=settings, stream_fn=fake_stream),
        calendar_reader=lambda: [],
        inbox_reader=lambda: {"unread": 0, "recent": []},
    )


def _turn(ws: Any, text: str) -> list[dict[str, Any]]:
    ws.send_json({"type": "text", "text": text})
    events: list[dict[str, Any]] = []
    while True:
        ev = ws.receive_json()
        events.append(ev)
        if ev["type"] == "error" or (ev["type"] == "done" and not ev.get("first_wake")):
            return events


def test_slow_local_model_announces_itself() -> None:
    import asyncio
    import tempfile

    async def slow_stream(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        await asyncio.sleep(SLOW_AFTER_S * 3)
        yield {"type": "sentence", "text": "Oi!"}
        yield {"type": "result", "text": "Oi!", "raw_text": "Oi!", "emotion": "neutral"}

    with tempfile.TemporaryDirectory() as tmp, TestClient(_app(Path(tmp), slow_stream)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
            ws.receive_json()
            events = _turn(ws, "oi")
    notices = [e for e in events if e["type"] == "notice"]
    assert len(notices) == 1 and notices[0]["kind"] == "slow_model" and notices[0]["text"]


def test_no_notice_after_a_failed_turn() -> None:
    import tempfile

    async def failing_stream(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        raise LLMError("boom")
        yield {}  # pragma: no cover

    async def quick_stream(**_kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        yield {"type": "result", "text": "ok", "raw_text": "ok", "emotion": "neutral"}

    mode = {"fail": True}

    async def stream(**kwargs: Any) -> AsyncIterator[dict[str, Any]]:
        source = failing_stream if mode["fail"] else quick_stream
        async for item in source(**kwargs):
            yield item

    with tempfile.TemporaryDirectory() as tmp, TestClient(_app(Path(tmp), stream)) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
            ws.receive_json()
            first = _turn(ws, "oi")
            assert first[-1]["type"] == "error"
            time.sleep(SLOW_AFTER_S * 2)  # a leaked timer would fire now
            mode["fail"] = False
            second = _turn(ws, "de novo")
    assert not [e for e in second if e["type"] == "notice"]
