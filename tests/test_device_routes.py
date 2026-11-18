"""Tests for the device REST routes: list, role/name/layout updates, priority order and actions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.device_hub import DeviceHub
from app.device_routes import setup_devices


def _require_testclient(request: Request) -> None:
    if request.client is None or request.client.host != "testclient":
        raise HTTPException(status_code=403, detail="Mac only.")


def _always_deny(request: Request) -> None:
    raise HTTPException(status_code=403, detail="Mac only.")


def _app(tmp_path: Path, require: Any = _require_testclient) -> tuple[FastAPI, DeviceHub]:
    app = FastAPI()
    hub = setup_devices(app, tmp_path / "devices.db", require)
    return app, hub


def _hello(hub: DeviceHub, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Open a fake connection through the hub; return its entry and the messages it received."""
    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    body_info: dict[str, Any] = {}
    asyncio.run(hub.hello(body_info, data, send))
    return body_info["entry"], messages


def test_get_devices_lists_connected_device_after_hello(tmp_path: Path) -> None:
    app, hub = _app(tmp_path)
    _hello(hub, {"body": "esp32", "device_id": "route-dev-0001", "name": "Desk"})
    client = TestClient(app)

    response = client.get("/api/devices")

    assert response.status_code == 200
    [device] = response.json()["devices"]
    assert device["id"] == "route-dev-0001"
    assert device["name"] == "Desk"
    assert device["roles"] == ["panel"]
    assert device["connected"] is True
    assert device["active"] is False


def test_put_roles_takes_effect_and_notifies_the_connected_device(tmp_path: Path) -> None:
    app, hub = _app(tmp_path)
    _, messages = _hello(hub, {"body": "esp32", "device_id": "route-dev-0002"})
    client = TestClient(app)

    response = client.put("/api/devices/route-dev-0002", json={"roles": ["body"]})

    assert response.status_code == 200
    assert response.json()["roles"] == ["body"]
    assert any(m.get("type") == "role" and m["roles"] == ["body"] for m in messages)
    [device] = client.get("/api/devices").json()["devices"]
    assert device["active"] is True


def test_put_unknown_device_is_404(tmp_path: Path) -> None:
    app, _ = _app(tmp_path)
    client = TestClient(app)

    response = client.put("/api/devices/missing-dev-9999", json={"name": "Ghost"})

    assert response.status_code == 404


def test_put_invalid_role_is_422(tmp_path: Path) -> None:
    app, hub = _app(tmp_path)
    _hello(hub, {"body": "esp32", "device_id": "route-dev-0003"})
    client = TestClient(app)

    response = client.put("/api/devices/route-dev-0003", json={"roles": ["wizard"]})

    assert response.status_code == 422
    assert "roles" in response.json()["detail"]


def test_explicit_null_clears_layout_and_omitted_field_keeps_it(tmp_path: Path) -> None:
    app, hub = _app(tmp_path)
    _hello(hub, {"body": "esp32", "device_id": "route-dev-0004"})
    client = TestClient(app)
    url = "/api/devices/route-dev-0004"

    response = client.put(url, json={"layout_id": "desk-wide"})
    assert response.json()["layout_id"] == "desk-wide"

    response = client.put(url, json={"name": "Renamed"})
    assert response.json()["layout_id"] == "desk-wide"
    assert response.json()["name"] == "Renamed"

    response = client.put(url, json={"layout_id": None})
    assert response.status_code == 200
    assert response.json()["layout_id"] is None


def test_priority_endpoint_sets_order_and_returns_device_list(tmp_path: Path) -> None:
    app, hub = _app(tmp_path)
    _hello(hub, {"body": "esp32", "device_id": "route-prio-0001"})
    _hello(hub, {"body": "esp32", "device_id": "route-prio-0002"})
    client = TestClient(app)

    response = client.put(
        "/api/devices/priority",
        json={"order": ["route-prio-0002", "route-prio-0001"]},
    )

    assert response.status_code == 200
    devices = {device["id"]: device for device in response.json()["devices"]}
    assert devices["route-prio-0002"]["body_priority"] == 0
    assert devices["route-prio-0001"]["body_priority"] == 1


def test_mutating_routes_are_forbidden_off_the_mac_but_get_still_works(tmp_path: Path) -> None:
    app, _ = _app(tmp_path, require=_always_deny)
    client = TestClient(app)

    assert client.get("/api/devices").status_code == 200
    assert client.get("/api/actions").status_code == 200
    assert client.put("/api/devices/priority", json={"order": []}).status_code == 403
    assert client.put("/api/devices/some-device-0001", json={"name": "x"}).status_code == 403


def test_get_actions_lists_registered_actions(tmp_path: Path) -> None:
    app, hub = _app(tmp_path)
    hub.actions.register("device.ping", lambda args: None, "Ping the device")
    client = TestClient(app)

    response = client.get("/api/actions")

    assert response.status_code == 200
    assert response.json() == {"actions": [{"id": "device.ping", "description": "Ping the device"}]}
