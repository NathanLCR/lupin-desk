"""Registry of named actions that devices may invoke by ID.

Devices send ``{"type": "action", "id": "<action-id>", "args": {...}}``. The
Brain only ever runs handlers that Brain code registered under an ID; devices
never send commands. Arguments are passed to the handler as data and are never
logged or echoed back in replies.
"""

from __future__ import annotations

import inspect
import logging
import re
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")

_MAX_REPLY_ID_LEN = 64


def _reply_id(action_id: object) -> str | None:
    """Return the action id for a reply, truncated, or None when it is not a str."""
    if isinstance(action_id, str):
        return action_id[:_MAX_REPLY_ID_LEN]
    return None


class ActionRegistry:
    """Maps action IDs to Brain-side handlers and runs them on request."""

    def __init__(self) -> None:
        self._handlers: dict[str, Callable[[dict[str, Any]], Any]] = {}
        self._descriptions: dict[str, str] = {}

    def register(
        self,
        action_id: str,
        handler: Callable[[dict[str, Any]], Any],
        description: str = "",
    ) -> None:
        """Register a sync or async handler under ``action_id``.

        Raises ValueError if the ID is malformed or already registered.
        """
        if not isinstance(action_id, str) or not ACTION_ID_RE.fullmatch(action_id):
            raise ValueError(f"Invalid action id: {action_id!r}")
        if action_id in self._handlers:
            raise ValueError(f"Action already registered: {action_id!r}")
        if not callable(handler):
            raise TypeError("Action handler must be callable")
        self._handlers[action_id] = handler
        self._descriptions[action_id] = description

    def has(self, action_id: object) -> bool:
        """Return True if ``action_id`` is a registered action."""
        return isinstance(action_id, str) and action_id in self._handlers

    def list(self) -> list[dict[str, str]]:
        """Return registered actions as ``{"id", "description"}`` dicts sorted by id."""
        return [
            {"id": action_id, "description": self._descriptions[action_id]}
            for action_id in sorted(self._handlers)
        ]

    async def run(self, action_id: object, args: object) -> dict[str, Any]:
        """Run a registered action and return an ``action_result`` reply dict.

        The reply never contains ``args``, and logs never contain them either.
        """
        if not self.has(action_id):
            reply_id = _reply_id(action_id)
            logger.warning("Rejected unknown action id %r", reply_id)
            return {
                "type": "action_result",
                "id": reply_id,
                "ok": False,
                "error": "unknown_action",
            }

        assert isinstance(action_id, str)  # narrowed by has()

        if args is None:
            args = {}
        if not isinstance(args, dict):
            return {
                "type": "action_result",
                "id": action_id,
                "ok": False,
                "error": "invalid_args",
            }

        handler = self._handlers[action_id]
        try:
            value = handler(args)
            if inspect.isawaitable(value):
                value = await value
        except Exception as exc:
            # Log the action id and exception type only: the exception message
            # may echo the args, and args must not reach the logs.
            logger.error(
                "Action %r failed with %s", action_id, type(exc).__name__
            )
            return {
                "type": "action_result",
                "id": action_id,
                "ok": False,
                "error": "action_failed",
            }

        reply: dict[str, Any] = {"type": "action_result", "id": action_id, "ok": True}
        if value is not None:
            reply["result"] = value
        return reply
