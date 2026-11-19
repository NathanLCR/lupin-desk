"""HTTP routes and Panel actions for the Control Deck.

Everything that creates or changes a macro, webhook or rule is Mac-only (loopback peer, Host and
Origin checked, as in app/mcp_routes.py). Webhooks are received on ``/hooks/<secret>`` from the
LAN: the secret in the path is the credential. It is never logged and never returned to a
device other than the Mac.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.control.engine import MacroRunner
from app.control.store import VALUE_MAX_CHARS, ControlStore
from app.control.system import SystemControl
from app.mcp_server import _security_error
from app.signals import Importance, Signal

logger = logging.getLogger(__name__)

_MAC_ONLY_DETAIL = "The Control Deck can only be configured on the Mac."
MAX_HOOK_BODY_BYTES = 4096
HOOK_WINDOW_SECONDS = 60.0
HOOK_MAX_PER_WINDOW = 60

Publish = Callable[[str, dict[str, Any]], Awaitable[Any]]


class MacroBody(BaseModel):
    name: str | None = None
    steps: list[dict[str, Any]] | None = None


class WebhookBody(BaseModel):
    name: str
    emit_signal: bool = True


class RuleBody(BaseModel):
    trigger: str
    match: str
    page_id: str


class RulePatch(BaseModel):
    enabled: bool | None = None
    trigger: str | None = None
    match: str | None = None
    page_id: str | None = None


def _id_arg(args: dict[str, Any], key: str = "id") -> int:
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be a whole number")
    return value


def setup_actions(
    actions: Any,
    system: SystemControl,
    runner: MacroRunner,
    *,
    shortcuts: Any,
    mac: Any,
) -> None:
    """Register the Control Deck actions. Handlers raise ValueError for bad arguments."""

    def reg(action_id: str, handler: Callable[[dict[str, Any]], Any], text: str) -> None:
        actions.register(action_id, handler, text)

    async def off_loop(fn: Callable[..., Any], *a: Any) -> Any:
        return await asyncio.to_thread(fn, *a)

    reg("volume.up", lambda args: off_loop(system.volume, "up"), "Raise the Mac volume.")
    reg("volume.down", lambda args: off_loop(system.volume, "down"), "Lower the Mac volume.")
    reg("volume.mute", lambda args: off_loop(system.volume, "mute"), "Toggle Mac output mute.")
    reg("mic.toggle", lambda args: off_loop(system.mic_toggle), "Toggle microphone mute.")
    # Media keys already exist as media.play_pause / media.next / media.previous (app/panels/everyday.py).

    async def macro_run(args: dict[str, Any]) -> dict[str, Any]:
        return await runner.run(_id_arg(args))

    reg("macro.run", macro_run, "Run a saved macro by id.")

    async def shortcut_run(args: dict[str, Any]) -> dict[str, Any]:
        slug = args.get("slug")
        if not isinstance(slug, str):
            raise ValueError("slug must be text")
        shortcut = shortcuts.get_shortcut(slug)
        if shortcut is None:
            raise ValueError("unknown shortcut")
        # Confirmation-gated shortcuts and agent prompts never run from a Panel tap or a macro.
        if shortcut.get("requires_confirmation") or shortcut.get("action_type") == "agent_prompt":
            raise ValueError("shortcut is not allowed here")
        result = await asyncio.to_thread(mac.run_shortcut, shortcut)
        return {"ok": bool(result.get("ok"))}

    reg("shortcut.run", shortcut_run, "Run a saved Shortcut by slug.")

    async def app_activate(args: dict[str, Any]) -> dict[str, Any]:
        name = args.get("name")
        if not isinstance(name, str) or mac.validate_app_name(name) is None:
            raise ValueError("invalid app name")
        # Only apps that are open now or saved Dock favorites: never an arbitrary installed app.
        known = await asyncio.to_thread(mac.list_running_apps)
        by_lower = {str(a.get("name", "")).lower(): str(a["name"]) for a in known if a.get("name")}
        canonical = by_lower.get(name.strip().lower())
        if canonical is None:
            raise ValueError("app is not in the Dock")
        result = await asyncio.to_thread(mac.activate_app, canonical)
        return {"ok": bool(result.get("ok"))}

    reg("app.activate", app_activate, "Bring a Mac app to the front.")


def setup_routes(
    app: FastAPI,
    store: ControlStore,
    system: SystemControl,
    require_mac_client: Callable[..., Any],
    publish: Publish,
    signals: Callable[[], Any],
    *,
    clock: Callable[[], float] = time.monotonic,
) -> None:
    def _guard(request: Request) -> None:
        # Loopback peer plus Host/Origin checks: defence against DNS rebinding, as in mcp_routes.
        require_mac_client(request, _MAC_ONLY_DETAIL)
        if _security_error(request) is not None:
            raise HTTPException(status_code=403, detail=_MAC_ONLY_DETAIL)

    def _write_guard(request: Request) -> None:
        _guard(request)
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(status_code=415, detail="Send application/json.")

    def _delete_guard(request: Request) -> None:
        _guard(request)

    def _is_mac(request: Request) -> bool:
        try:
            _guard(request)
        except HTTPException:
            return False
        return True

    def _bad(exc: ValueError) -> HTTPException:
        return HTTPException(status_code=400, detail=str(exc))

    write = [Depends(_write_guard)]
    delete = [Depends(_delete_guard)]

    # ------------------------------------------------------------------ audio

    @app.get("/api/control/audio")
    async def get_audio() -> dict[str, Any]:
        return await asyncio.to_thread(system.status)

    # ----------------------------------------------------------------- macros

    @app.get("/api/control/macros")
    async def list_macros() -> dict[str, Any]:
        return {"macros": store.list_macros()}

    @app.post("/api/control/macros", dependencies=write)
    async def create_macro(body: MacroBody) -> dict[str, Any]:
        try:
            return {"macro": store.add_macro(body.name, body.steps)}
        except ValueError as exc:
            raise _bad(exc) from exc

    @app.patch("/api/control/macros/{macro_id}", dependencies=write)
    async def patch_macro(macro_id: int, body: MacroBody) -> dict[str, Any]:
        try:
            macro = store.update_macro(macro_id, body.name, body.steps)
        except ValueError as exc:
            raise _bad(exc) from exc
        if macro is None:
            raise HTTPException(status_code=404, detail="Unknown macro.")
        return {"macro": macro}

    @app.delete("/api/control/macros/{macro_id}", dependencies=delete)
    async def delete_macro(macro_id: int) -> dict[str, Any]:
        if not store.remove_macro(macro_id):
            raise HTTPException(status_code=404, detail="Unknown macro.")
        return {"deleted": True, "id": macro_id}

    # --------------------------------------------------------------- webhooks

    @app.get("/api/control/webhooks")
    async def list_webhooks(request: Request) -> dict[str, Any]:
        # Only the Mac sees the secret paths; the Panels get names and last values.
        return {"webhooks": store.list_webhooks(with_secret=_is_mac(request))}

    @app.post("/api/control/webhooks", dependencies=write)
    async def create_webhook(body: WebhookBody) -> dict[str, Any]:
        try:
            return {"webhook": store.add_webhook(body.name, body.emit_signal)}
        except ValueError as exc:
            raise _bad(exc) from exc

    @app.post("/api/control/webhooks/{hook_id}/rotate", dependencies=write)
    async def rotate_webhook(hook_id: int) -> dict[str, Any]:
        hook = store.rotate_webhook(hook_id)
        if hook is None:
            raise HTTPException(status_code=404, detail="Unknown webhook.")
        return {"webhook": hook}

    @app.delete("/api/control/webhooks/{hook_id}", dependencies=delete)
    async def delete_webhook(hook_id: int) -> dict[str, Any]:
        if not store.remove_webhook(hook_id):
            raise HTTPException(status_code=404, detail="Unknown webhook.")
        return {"deleted": True, "id": hook_id}

    hits: dict[int, deque[float]] = {}

    def _rate_ok(hook_id: int) -> bool:
        now = clock()
        window = hits.setdefault(hook_id, deque())
        while window and now - window[0] > HOOK_WINDOW_SECONDS:
            window.popleft()
        if len(window) >= HOOK_MAX_PER_WINDOW:
            return False
        window.append(now)
        return True

    @app.post("/hooks/{secret}")
    async def receive_webhook(secret: str, request: Request) -> JSONResponse:
        hook = store.find_webhook_by_secret(secret)
        if hook is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        if not _rate_ok(hook["id"]):
            return JSONResponse({"error": "rate_limited"}, status_code=429)
        raw = b""
        async for chunk in request.stream():
            raw += chunk
            if len(raw) > MAX_HOOK_BODY_BYTES:
                return JSONResponse({"error": "too_large"}, status_code=413)
        value: str | None = None
        if raw.strip():
            try:
                body = json.loads(raw)
            except ValueError:
                return JSONResponse({"error": "bad_json"}, status_code=400)
            candidate = body.get("value") if isinstance(body, dict) else body
            if isinstance(candidate, bool):
                value = "true" if candidate else "false"
            elif isinstance(candidate, (str, int, float)):
                value = str(candidate)[:VALUE_MAX_CHARS]
        updated = store.record_webhook_value(hook["id"], value)
        if updated is None:
            return JSONResponse({"error": "not_found"}, status_code=404)
        try:
            await publish("webhooks", {"id": updated["id"], "name": updated["name"],
                                       "value": updated["value"], "at": updated["at"]})
        except Exception as exc:
            logger.warning("A webhook update was not published (%s).", type(exc).__name__)
        bus = signals()
        if hook["emit_signal"] and bus is not None:
            try:
                # The value never goes into the Signal: it stays on the widget topic.
                await bus.emit(Signal(kind=f"webhook.{hook['id']}", source="webhook",
                                      importance=Importance.LOW, data={"hook": hook["id"]}))
            except Exception as exc:
                logger.warning("A webhook Signal was not emitted (%s).", type(exc).__name__)
        return JSONResponse({"ok": True})

    # ------------------------------------------------------------------ rules

    @app.get("/api/control/rules", dependencies=delete)
    async def list_rules() -> dict[str, Any]:
        return {"rules": store.list_rules()}

    @app.post("/api/control/rules", dependencies=write)
    async def create_rule(body: RuleBody) -> dict[str, Any]:
        try:
            return {"rule": store.add_rule(body.trigger, body.match, body.page_id)}
        except ValueError as exc:
            raise _bad(exc) from exc

    @app.patch("/api/control/rules/{rule_id}", dependencies=write)
    async def patch_rule(rule_id: int, body: RulePatch) -> dict[str, Any]:
        try:
            rule = store.update_rule(rule_id, body.trigger, body.match, body.page_id)
            if rule is not None and body.enabled is not None:
                rule = store.set_rule_enabled(rule_id, body.enabled)
        except ValueError as exc:
            raise _bad(exc) from exc
        if rule is None:
            raise HTTPException(status_code=404, detail="Unknown rule.")
        return {"rule": rule}

    @app.delete("/api/control/rules/{rule_id}", dependencies=delete)
    async def delete_rule(rule_id: int) -> dict[str, Any]:
        if not store.remove_rule(rule_id):
            raise HTTPException(status_code=404, detail="Unknown rule.")
        return {"deleted": True, "id": rule_id}
