"""Macro runner and rules engine for the Control Deck.

Macros run only the whitelisted action IDs of ``MACRO_ACTIONS``, through the ActionRegistry.
Rules have two triggers, "app in front" and "Signal received", and the one effect "switch the
Panel to a page" (published on the hub topic ``panel:goto``).

Privacy: the front app is read live, only while an enabled "app in front" rule exists, only
its name is compared, and neither the name nor the title is stored or logged. A rule works
fully on the Mac and sends nothing to an LLM, so it needs no front app Data Consent. The only
thing kept between two reads is the id of the rule that matched last, to switch once per change.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.control.store import MACRO_ACTIONS, ControlStore

logger = logging.getLogger(__name__)

GOTO_TOPIC = "panel:goto"
POLL_SECONDS = 3.0

Sleep = Callable[[float], Awaitable[Any]]


class MacroRunner:
    def __init__(self, store: ControlStore, actions: Any, *, sleep: Sleep = asyncio.sleep) -> None:
        self._store = store
        self._actions = actions
        self._sleep = sleep
        self._running: set[int] = set()

    async def run(self, macro_id: int) -> dict[str, Any]:
        """Run a macro one step after the other; stop at the first step that fails."""
        macro = self._store.get_macro(macro_id)
        if macro is None:
            raise ValueError("unknown macro id")
        if macro_id in self._running:
            raise ValueError("macro is already running")
        self._running.add(macro_id)
        ran = 0
        try:
            for step in macro["steps"]:
                action = step["action"]
                if action not in MACRO_ACTIONS or not self._actions.has(action):
                    return {"id": macro_id, "ok": False, "ran": ran}
                reply = await self._actions.run(action, dict(step.get("args") or {}))
                if not reply.get("ok"):
                    return {"id": macro_id, "ok": False, "ran": ran}
                ran += 1
                if step.get("delay_ms"):
                    await self._sleep(step["delay_ms"] / 1000.0)
        finally:
            self._running.discard(macro_id)
        return {"id": macro_id, "ok": True, "ran": ran}


class RulesEngine:
    def __init__(
        self,
        store: ControlStore,
        publish: Callable[[str, dict[str, Any]], Awaitable[Any]],
        front_app: Callable[[], dict[str, str] | None] | None,
        *,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._store = store
        self._publish = publish
        self._front_app = front_app
        self._poll_seconds = poll_seconds
        self._last_rule: int | None = None
        self._task: asyncio.Task[None] | None = None

    async def _goto(self, page_id: str) -> None:
        try:
            await self._publish(GOTO_TOPIC, {"page_id": page_id})
        except Exception as exc:
            logger.warning("A rule could not switch the Panel page (%s).", type(exc).__name__)

    async def on_signal(self, signal: Any) -> None:
        """Signal listener: switch the page of every enabled rule for this kind."""
        kind = getattr(signal, "kind", None)
        for rule in self._store.enabled_rules():
            if rule["trigger"] == "signal" and rule["match"] == kind:
                await self._goto(rule["page_id"])

    async def tick(self) -> bool:
        """Read the front app once and apply the matching rule. True when a page was switched."""
        rules = [r for r in self._store.enabled_rules() if r["trigger"] == "app_front"]
        if not rules or self._front_app is None:
            self._last_rule = None
            return False
        try:
            info = await asyncio.to_thread(self._front_app)
        except Exception:
            info = None
        name = str((info or {}).get("name") or "").strip().lower()
        info = None  # the title is never looked at, and nothing keeps the result
        matched = next((r for r in rules if name and r["match"].strip().lower() == name), None)
        name = ""
        if matched is None:
            self._last_rule = None
            return False
        if matched["id"] == self._last_rule:
            return False
        self._last_rule = matched["id"]
        await self._goto(matched["page_id"])
        return True

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.get_running_loop().create_task(self._loop())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.warning("Rules tick failed (%s).", type(exc).__name__)
            await asyncio.sleep(self._poll_seconds)
