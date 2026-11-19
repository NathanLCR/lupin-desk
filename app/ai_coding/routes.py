"""HTTP routes for AI coding: the snapshot, the hook receivers and hook install/remove."""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.ai_coding.hooks import HooksError
from app.mcp_server import _security_error

logger = logging.getLogger(__name__)

MAX_HOOK_BODY_BYTES = 1024 * 1024
MAC_ONLY_DETAIL = "Claude Code hooks can only be managed on the Mac."
WAITING_NOTIFICATIONS = frozenset({"idle_prompt", "elicitation_dialog"})


def setup_routes(app: FastAPI, service: Any) -> None:
    def guard(request: Request, *, write: bool) -> None:
        # Loopback peer, loopback Host and loopback Origin: defends against DNS rebinding.
        if _security_error(request) is not None:
            raise HTTPException(status_code=403, detail=MAC_ONLY_DETAIL)
        if write:
            kind = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if kind != "application/json":
                raise HTTPException(status_code=415, detail="Send application/json.")

    async def hook_body(request: Request) -> dict[str, Any]:
        guard(request, write=True)
        chunks: list[bytes] = []
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > MAX_HOOK_BODY_BYTES:
                raise HTTPException(status_code=413, detail="Too large.")
            chunks.append(chunk)
        try:
            data = json.loads(b"".join(chunks) or b"{}")
        except (ValueError, RecursionError):
            raise HTTPException(status_code=400, detail="Bad JSON.") from None
        if not isinstance(data, dict):
            raise HTTPException(status_code=400, detail="Bad JSON.")
        return data

    @app.get("/api/ai-coding/snapshot")
    async def snapshot() -> dict[str, Any]:
        return await service.snapshot()

    @app.get("/api/claude-hooks")
    async def hooks_status(request: Request) -> dict[str, Any]:
        guard(request, write=False)
        try:
            return service.installer.status()
        except HooksError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/api/claude-hooks/install")
    async def hooks_install(request: Request) -> dict[str, Any]:
        guard(request, write=True)
        try:
            return service.installer.install()
        except HooksError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/api/claude-hooks/remove")
    async def hooks_remove(request: Request) -> dict[str, Any]:
        guard(request, write=True)
        try:
            return service.installer.remove()
        except HooksError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None

    @app.post("/api/claude-hooks/permission")
    async def hook_permission(request: Request) -> JSONResponse:
        data = await hook_body(request)
        session = str(data.get("session_id") or "unknown")
        await service.broker.session_active(session)
        output = await service.broker.request(
            session, str(data.get("cwd") or ""), data.get("tool_name"), data.get("tool_input")
        )
        return JSONResponse(output)

    @app.post("/api/claude-hooks/event")
    async def hook_event(request: Request) -> JSONResponse:
        data = await hook_body(request)
        session = str(data.get("session_id") or "unknown")
        event = data.get("hook_event_name")
        if event == "Stop" or (
            event == "Notification" and data.get("notification_type") in WAITING_NOTIFICATIONS
        ):
            await service.broker.wait_for_user(session)
        return JSONResponse({})
