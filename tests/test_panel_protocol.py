"""Device Roles over the real /ws and REST (P01, docs/brain-body-protocol.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MAC_IP = "192.168.0.10"


def _client(tmp_path: Path) -> tuple[Any, TestClient]:
    settings = Settings(
        db_path=tmp_path / "memory.db",
        cowork_workspace_path=tmp_path / "Cowork",
        llm_api_key="test-key",
    )
    app = create_app(settings=settings, local_ips=lambda: frozenset({"testclient"}))
    return app, TestClient(app)


def test_new_device_is_a_panel_and_roles_change_live(tmp_path: Path) -> None:
    app, client = _client(tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "web", "protocol": 1, "device_id": "dev-aaaa1111", "name": "Old iPad"})
        welcome = ws.receive_json()
        assert welcome["roles"] == ["panel"]
        assert welcome["active"] is False and welcome["active_body"] is None

        devices = client.get("/api/devices").json()["devices"]
        assert devices[0]["id"] == "dev-aaaa1111" and devices[0]["connected"] is True

        res = client.put("/api/devices/dev-aaaa1111", json={"roles": ["body", "panel"]})
        assert res.status_code == 200
        role = ws.receive_json()
        assert role["type"] == "role" and role["roles"] == ["body", "panel"] and role["active"] is True
        assert ws.receive_json()["type"] == "active_body"


def test_priority_and_failover_between_two_bodies(tmp_path: Path) -> None:
    app, client = _client(tmp_path)
    with client.websocket_connect("/ws") as low, client.websocket_connect("/ws") as high:
        low.send_json({"type": "hello", "body": "web", "device_id": "dev-low00001"})
        low.receive_json()
        client.put("/api/devices/dev-low00001", json={"roles": ["body"]})
        high.send_json({"type": "hello", "body": "web", "device_id": "dev-high0001"})
        high.receive_json()
        client.put("/api/devices/dev-high0001", json={"roles": ["body"]})
        client.put("/api/devices/priority", json={"order": ["dev-high0001", "dev-low00001"]})
        active = app.state.device_hub.current_active_body()
        assert active["device_id"] == "dev-high0001"


def test_topics_and_actions_over_ws(tmp_path: Path) -> None:
    app, client = _client(tmp_path)
    calls: list[dict[str, Any]] = []
    app.state.actions.register("test.ping", lambda args: calls.append(args) or "pong")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "web", "device_id": "dev-cccc3333"})
        ws.receive_json()
        ws.send_json({"type": "subscribe", "topics": ["clock", "Bad Topic"]})
        assert ws.receive_json() == {"type": "subscribed", "topics": ["clock"]}

        ws.send_json({"type": "action", "id": "test.ping", "args": {"a": 1}})
        reply = ws.receive_json()
        assert reply["ok"] is True and reply["result"] == "pong" and calls == [{"a": 1}]

        ws.send_json({"type": "action", "id": "mac.shell", "args": {"cmd": "rm -rf /"}})
        reply = ws.receive_json()
        assert reply["ok"] is False and reply["error"] == "unknown_action"
        assert "rm -rf" not in str(reply)


def test_legacy_hello_without_device_id_is_still_a_body(tmp_path: Path) -> None:
    app, client = _client(tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "body": "rg406h-web", "protocol": 1})
        welcome = ws.receive_json()
        assert welcome["active"] is True and "device_id" not in welcome
    assert client.get("/api/devices").json()["devices"] == []


def test_role_edit_is_mac_only(tmp_path: Path) -> None:
    settings = Settings(db_path=tmp_path / "m.db", cowork_workspace_path=tmp_path / "C", llm_api_key="k")
    app = create_app(settings=settings, local_ips=lambda: frozenset({MAC_IP}))
    app.state.device_store.upsert_hello("dev-dddd4444", name="x")

    async def from_phone(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await app({**scope, "client": ("192.168.0.77", 5000)}, receive, send)

    client = TestClient(from_phone)
    assert client.get("/api/devices").status_code == 200
    res = client.put("/api/devices/dev-dddd4444", json={"roles": ["body"]})
    assert res.status_code == 403
