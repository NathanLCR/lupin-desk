"""Issue 12 end to end: /mcp is mounted, and external MCP tools go through the approval flow.

These tests need the `12-main.py.diff` and `12-llm.py.diff` patches applied.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "fake_mcp_server.py"
HEADERS = {"host": "127.0.0.1:8000", "content-type": "application/json"}


class _McpLLM:
    def __init__(self, target: str) -> None:
        self.target = target

    async def stream_chat(self, **kwargs: Any):
        self.skills_context = kwargs.get("skills_context", "")
        yield {"type": "emotion", "emotion": "neutral"}
        yield {"type": "action", "kind": "mcp", "target": self.target}
        yield {"type": "delta", "text": "Pronto."}
        yield {"type": "sentence", "text": "Pronto."}
        yield {"type": "done"}


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        db_path=tmp_path / "test.db",
        cowork_workspace_path=tmp_path / "missing-cowork",
        host="127.0.0.1",
    )


def _add_fixture_server(client: TestClient) -> None:
    res = client.post(
        "/api/mcp/servers",
        json={"id": "fake", "name": "Fake", "transport": "stdio", "command": [sys.executable, str(FIXTURE)]},
    )
    assert res.status_code in (200, 201), res.text
    assert client.post("/api/mcp/servers/fake/refresh").status_code == 200


def _wait(ws: Any, kind: str) -> dict[str, Any]:
    for _ in range(25):
        msg = ws.receive_json()
        if msg.get("type") == kind:
            return msg
    raise AssertionError(f"{kind} not received")


def test_mcp_endpoint_is_mounted(tmp_path: Path) -> None:
    with TestClient(create_app(settings=_settings(tmp_path))) as client:
        res = client.post("/mcp", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert res.status_code == 200
        names = {t["name"] for t in res.json()["result"]["tools"]}
        assert "lupin_say" in names


def test_external_tool_needs_approval_by_default_then_runs(tmp_path: Path) -> None:
    llm = _McpLLM('fake.echo {"text": "hello"}')
    with TestClient(create_app(settings=_settings(tmp_path), llm_client=llm)) as client:  # type: ignore[arg-type]
        _add_fixture_server(client)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "use the tool"})
            req = _wait(ws, "tool_approval_request")
            assert req["kind"] == "mcp" and req["risk"] == "external"
            assert "hello" not in req["message"]
            ws.send_json({"type": "confirm_action", "approval_id": req["approval_id"], "approved": True})
            done = _wait(ws, "action_executed")
            assert done["ok"] is True
            assert "untrusted data" in done["result"]


def test_external_tool_declined_does_not_run(tmp_path: Path) -> None:
    llm = _McpLLM('fake.echo {"text": "hello"}')
    with TestClient(create_app(settings=_settings(tmp_path), llm_client=llm)) as client:  # type: ignore[arg-type]
        _add_fixture_server(client)
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "use the tool"})
            req = _wait(ws, "tool_approval_request")
            ws.send_json({"type": "confirm_action", "approval_id": req["approval_id"], "approved": False})
            done = _wait(ws, "action_executed")
            assert done["ok"] is False and done["cancelled"] is True


def test_read_tool_runs_without_approval_and_prompt_lists_tools(tmp_path: Path) -> None:
    llm = _McpLLM('fake.echo {"text": "hello"}')
    with TestClient(create_app(settings=_settings(tmp_path), llm_client=llm)) as client:  # type: ignore[arg-type]
        _add_fixture_server(client)
        res = client.put("/api/mcp/servers/fake/tools/echo/risk", json={"risk": "read"})
        assert res.status_code == 200
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "use the tool"})
            done = _wait(ws, "action_executed")
            assert done["ok"] is True and done["kind"] == "mcp"
        assert "fake.echo" in llm.skills_context


def test_unknown_external_tool_is_refused(tmp_path: Path) -> None:
    llm = _McpLLM("nope.tool {}")
    with TestClient(create_app(settings=_settings(tmp_path), llm_client=llm)) as client:  # type: ignore[arg-type]
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "x"})
            done = _wait(ws, "action_executed")
            assert done["ok"] is False
