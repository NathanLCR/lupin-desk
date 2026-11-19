"""Permission prompts from Claude Code, answered on a Panel.

A hook asks `request()`; the Brain shows the prompt on the Panels that are subscribed to the
prompts topic and waits (2 minutes). Allow or Deny is accepted only from a connection that is
showing that prompt right now, once, before it expires. A timeout or an unanswerable prompt
returns no decision, so Claude Code shows its own prompt. The tool and its arguments are sent
to Panels only; they are never logged and never put on the Signals bus.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.signals import Importance, Signal

logger = logging.getLogger(__name__)

PROMPTS_TOPIC = "ai-coding-prompts"
NEEDS_USER_KIND = "claude_code_needs_user"
NEEDS_USER_SOURCE = "claude_code"
PROMPT_TIMEOUT_SECONDS = 120.0
WAIT_HOLD_SECONDS = 120.0
MAX_ARGS_CHARS = 4000


def describe_tool(tool_name: Any, tool_input: Any) -> tuple[str, str]:
    """Return (tool, full command or arguments) for display."""
    tool = str(tool_name or "tool")[:80]
    if isinstance(tool_input, dict):
        for key in ("command", "file_path", "url", "pattern"):
            if isinstance(tool_input.get(key), str):
                return tool, tool_input[key][:MAX_ARGS_CHARS]
        try:
            return tool, json.dumps(tool_input, ensure_ascii=False)[:MAX_ARGS_CHARS]
        except (TypeError, ValueError):
            return tool, ""
    return tool, str(tool_input or "")[:MAX_ARGS_CHARS]


def needs_user_signal(prompt_id: str | None = None, **data: Any) -> Signal:
    """The "Claude needs the user" Signal. It asks the bus to hold the Expression until released."""
    fields: dict[str, Any] = {
        "kind": NEEDS_USER_KIND,
        "source": NEEDS_USER_SOURCE,
        "importance": Importance.IMPORTANT,
        "data": data,
    }
    try:
        return Signal(**fields, hold_expression=True, id=prompt_id)
    except TypeError:  # app/signals.py without the hold option (patch p09-signals not applied yet)
        return Signal(**fields)


@dataclass
class Prompt:
    id: str
    session_id: str
    project: str
    tool: str
    args: str
    expires_at: float
    future: asyncio.Future = field(repr=False)
    shown_to: list[dict[str, Any]] = field(default_factory=list, repr=False)

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "project": self.project,
            "tool": self.tool,
            "args": self.args,
            "expires_at": self.expires_at,
        }


class PermissionBroker:
    def __init__(
        self,
        get_hub: Callable[[], Any],
        get_bus: Callable[[], Any],
        *,
        timeout: float = PROMPT_TIMEOUT_SECONDS,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._get_hub = get_hub
        self._get_bus = get_bus
        self._timeout = timeout
        self._wall = wall_clock
        self._prompts: dict[str, Prompt] = {}
        self._waits: dict[str, asyncio.Task] = {}

    # -- viewers -----------------------------------------------------------

    def _viewers(self) -> list[dict[str, Any]]:
        hub = self._get_hub()
        if hub is None:
            return []
        return [e for e in list(hub.entries) if PROMPTS_TOPIC in (e.get("topics") or ())]

    def pending(self) -> list[Prompt]:
        return list(self._prompts.values())

    async def publish(self) -> None:
        """Send the pending prompts to each subscribed Panel and remember who was shown them."""
        for entry in self._viewers():
            visible = []
            for prompt in self._prompts.values():
                if not any(item is entry for item in prompt.shown_to):
                    prompt.shown_to.append(entry)
                visible.append(prompt.to_public())
            try:
                await entry["send"]({"type": "topic", "topic": PROMPTS_TOPIC, "data": {"prompts": visible}})
            except Exception:
                logger.info("A prompt update was not delivered to a Panel.")

    # -- the hook side -----------------------------------------------------

    async def request(self, session_id: str, cwd: str, tool_name: Any, tool_input: Any) -> dict[str, Any]:
        """Ask the user on a Panel; return the hook output ({} means "no decision")."""
        if not self._viewers():
            await self._emit_plain(session_id)
            return {}
        tool, args = describe_tool(tool_name, tool_input)
        prompt = Prompt(
            id=secrets.token_urlsafe(16),
            session_id=session_id[:80],
            project=(cwd.rstrip("/").rsplit("/", 1)[-1] if cwd else "")[:80],
            tool=tool,
            args=args,
            expires_at=self._wall() + self._timeout,
            future=asyncio.get_running_loop().create_future(),
        )
        self._prompts[prompt.id] = prompt
        await self._emit(prompt.id)
        await self.publish()
        decision: str | None = None
        try:
            decision = await asyncio.wait_for(asyncio.shield(prompt.future), self._timeout)
        except asyncio.TimeoutError:
            decision = None
        finally:
            self._prompts.pop(prompt.id, None)
            if not prompt.future.done():
                prompt.future.cancel()
            await self._release(prompt.id)
            await self.publish()
        if decision == "allow":
            return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": {"behavior": "allow"}}}
        if decision == "deny":
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PermissionRequest",
                    "decision": {"behavior": "deny", "message": "Denied from the Desk Assistant panel."},
                }
            }
        return {}

    async def wait_for_user(self, session_id: str) -> None:
        """A session stopped to wait for the user: Lupin says it once and holds the Expression."""
        key = f"wait:{session_id[:80]}"
        old = self._waits.pop(key, None)
        if old is not None:
            old.cancel()
        await self._emit(key)
        self._waits[key] = asyncio.create_task(self._release_later(key))

    async def session_active(self, session_id: str) -> None:
        """The session moved on (a new prompt was answered or sent): drop its waiting hold."""
        key = f"wait:{session_id[:80]}"
        task = self._waits.pop(key, None)
        if task is not None:
            task.cancel()
            await self._release(key)

    async def _release_later(self, key: str) -> None:
        try:
            await asyncio.sleep(WAIT_HOLD_SECONDS)
        except asyncio.CancelledError:
            return
        self._waits.pop(key, None)
        await self._release(key)

    async def stop(self) -> None:
        for task in list(self._waits.values()):
            task.cancel()
        self._waits.clear()

    # -- the Panel side ----------------------------------------------------

    def answer(self, entry: dict[str, Any] | None, prompt_id: Any, decision: Any) -> bool:
        """Accept an Allow or Deny. False (nothing changes) for anything not valid right now."""
        if entry is None or decision not in ("allow", "deny") or not isinstance(prompt_id, str):
            return False
        prompt = self._prompts.get(prompt_id)
        if prompt is None or prompt.future.done() or self._wall() >= prompt.expires_at:
            return False
        hub = self._get_hub()
        if hub is None or not any(item is entry for item in hub.entries):
            return False
        if not any(item is entry for item in prompt.shown_to):
            return False
        if PROMPTS_TOPIC not in (entry.get("topics") or ()):
            return False
        prompt.future.set_result(decision)
        return True

    # -- signals -----------------------------------------------------------

    async def _emit(self, hold_id: str) -> None:
        bus = self._get_bus()
        if bus is None:
            return
        try:
            await bus.emit(needs_user_signal(hold_id))
        except Exception as exc:
            logger.warning("The needs-user signal was not emitted (%s).", type(exc).__name__)

    async def _emit_plain(self, session_id: str) -> None:
        bus = self._get_bus()
        if bus is None:
            return
        try:
            await bus.emit(Signal(kind=NEEDS_USER_KIND, source=NEEDS_USER_SOURCE, importance=Importance.IMPORTANT))
        except Exception as exc:
            logger.warning("The needs-user signal was not emitted (%s).", type(exc).__name__)

    async def _release(self, hold_id: str) -> None:
        bus = self._get_bus()
        release = getattr(bus, "release", None)
        if release is None:
            return
        try:
            result = release(id=hold_id)
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.warning("A held expression was not released (%s).", type(exc).__name__)
