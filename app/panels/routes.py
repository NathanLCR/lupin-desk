"""HTTP routes for Layouts and the Panel page (P02, contract in the shared P02 brief)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, StrictInt

from app.config import BASE_DIR
from app.panels.layouts import LayoutStore
from app.panels.templates import list_templates

logger = logging.getLogger(__name__)


class ArrangeWidget(BaseModel):
    """One widget's position as sent by a device; config is never sent by a device."""

    id: str
    type: str
    x: StrictInt
    y: StrictInt
    w: StrictInt
    h: StrictInt


class ArrangeRequest(BaseModel):
    """A device's arrangement of one page variant."""

    page_id: str
    orientation: Literal["landscape", "portrait"]
    widgets: list[ArrangeWidget]


def register(
    fastapi_app: FastAPI,
    db_path: Path | str | None,
    require_mac_client: Callable[[Request], Any],
) -> LayoutStore:
    """Create the Layout store, register the Layout routes and the /panel page.

    ``require_mac_client(request)`` must raise HTTPException(403) for any client that is not
    the Mac; it guards create, save and delete. Arranging is open to every client.
    """
    store = LayoutStore(db_path)
    fastapi_app.state.layouts = store

    async def _announce(layout_id: str) -> None:
        hub = getattr(fastapi_app.state, "device_hub", None)
        if hub is None:
            return
        try:
            await hub.publish("layout", {"layout_id": layout_id})
        except Exception:
            logger.warning("Could not announce a layout change to the devices.")

    @fastapi_app.get("/panel")
    def panel_page() -> FileResponse:
        index_path = BASE_DIR / "static" / "panel" / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="Panel page not found.")
        return FileResponse(index_path)

    @fastapi_app.get("/editor")
    def editor_page(request: Request) -> FileResponse:
        require_mac_client(request)
        index_path = BASE_DIR / "static" / "editor" / "index.html"
        if not index_path.is_file():
            raise HTTPException(status_code=404, detail="Editor page not found.")
        return FileResponse(index_path)

    # Declared before the {layout_id} routes so the fixed path is never read as an id.
    @fastapi_app.get("/api/layout-templates")
    def list_layout_templates() -> dict[str, Any]:
        return {"templates": list_templates()}

    @fastapi_app.get("/api/layouts")
    def list_layouts() -> dict[str, Any]:
        return {"layouts": store.list()}

    @fastapi_app.post("/api/layouts", status_code=201)
    async def create_layout(payload: dict[str, Any], request: Request) -> dict[str, Any]:
        require_mac_client(request)
        try:
            layout = store.create(payload.get("name"), payload.get("template"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await _announce(layout["id"])
        return layout

    # Declared before PUT /api/layouts/{layout_id} (different path depth, kept explicit).
    @fastapi_app.put("/api/layouts/{layout_id}/arrange")
    async def arrange_layout(layout_id: str, payload: ArrangeRequest) -> dict[str, Any]:
        widgets = [widget.model_dump() for widget in payload.widgets]
        try:
            layout = store.arrange(layout_id, payload.page_id, payload.orientation, widgets)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Unknown page.") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if layout is None:
            raise HTTPException(status_code=404, detail="Unknown layout.")
        await _announce(layout["id"])
        return layout

    @fastapi_app.get("/api/layouts/{layout_id}")
    def get_layout(layout_id: str) -> dict[str, Any]:
        layout = store.get(layout_id)
        if layout is None:
            raise HTTPException(status_code=404, detail="Unknown layout.")
        return layout

    @fastapi_app.put("/api/layouts/{layout_id}")
    async def save_layout(
        layout_id: str, payload: dict[str, Any], request: Request
    ) -> dict[str, Any]:
        require_mac_client(request)
        try:
            layout = store.save(layout_id, payload)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if layout is None:
            raise HTTPException(status_code=404, detail="Unknown layout.")
        await _announce(layout["id"])
        return layout

    @fastapi_app.delete("/api/layouts/{layout_id}")
    def delete_layout(layout_id: str, request: Request) -> dict[str, Any]:
        require_mac_client(request)
        try:
            deleted = store.delete(layout_id)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        if not deleted:
            raise HTTPException(status_code=404, detail="Unknown layout.")
        return {"ok": True}

    return store
