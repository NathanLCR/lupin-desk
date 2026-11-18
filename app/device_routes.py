"""HTTP routes for the device registry (Bodies and Panels) and the action list."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app.actions import ActionRegistry
from app.device_hub import DeviceHub
from app.devices import DeviceStore


class DevicePriorityRequest(BaseModel):
    """Body Priority order: device IDs, highest priority first."""

    order: list[str]


class DeviceUpdateRequest(BaseModel):
    """User-editable device fields. Fields left out are kept; explicit nulls clear them."""

    name: str | None = None
    roles: list[str] | None = None
    layout_id: str | None = None
    body_priority: int | None = None


def setup_devices(
    fastapi_app: FastAPI,
    db_path: Path | str,
    require_mac_client: Callable[[Request], Any],
) -> DeviceHub:
    """Create the device store, action registry and hub, and register the device routes.

    ``require_mac_client(request)`` must raise HTTPException(403) for any client that is
    not the Mac; it guards every mutating route.
    """
    store = DeviceStore(db_path)
    actions = ActionRegistry()
    hub = DeviceHub(store, actions)

    fastapi_app.state.device_store = store
    fastapi_app.state.actions = actions
    fastapi_app.state.device_hub = hub
    fastapi_app.state.bodies = hub.entries

    def _devices_payload() -> dict[str, Any]:
        connected_ids = {entry["device_id"] for entry in hub.entries if entry.get("device_id")}
        active = hub.current_active_body()
        active_id = active.get("device_id") if active is not None else None
        devices = [
            {
                **record,
                "connected": record["id"] in connected_ids,
                "active": record["id"] == active_id,
            }
            for record in store.list()
        ]
        return {"devices": devices}

    @fastapi_app.get("/api/devices")
    def list_devices() -> dict[str, Any]:
        return _devices_payload()

    # Declared before the {device_id} route so "priority" is not read as an ID.
    @fastapi_app.put("/api/devices/priority")
    async def set_body_priority(
        payload: DevicePriorityRequest, request: Request
    ) -> dict[str, Any]:
        require_mac_client(request)
        store.set_body_priority_order(payload.order)
        await hub.device_changed()
        return _devices_payload()

    @fastapi_app.put("/api/devices/{device_id}")
    async def update_device(
        device_id: str, payload: DeviceUpdateRequest, request: Request
    ) -> dict[str, Any]:
        require_mac_client(request)
        if store.get(device_id) is None:
            raise HTTPException(status_code=404, detail="Unknown device.")

        fields = {field: getattr(payload, field) for field in payload.model_fields_set}
        try:
            updated = store.update(device_id, **fields)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if updated is None:
            raise HTTPException(status_code=404, detail="Unknown device.")

        await hub.device_changed(device_id)
        return updated

    @fastapi_app.get("/api/actions")
    def list_actions() -> dict[str, Any]:
        return {"actions": actions.list()}

    return hub
