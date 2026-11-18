"""Agent Requests: the transport-free core behind Lupin's local MCP server.

An agent on the Mac (Claude Code, for example) asks Lupin to do one of a few small things:
say a sentence, show an Expression, read Today, or post a Signal. This module holds the tool
catalogue, argument validation, the rate limit and the mapping onto the Signals bus. It knows
nothing about HTTP or JSON-RPC; `app/mcp_server.py` is the transport.

Rules this module enforces:

- Agents choose only the arguments declared in each tool's schema; any other key is refused.
- `lupin_read_today` returns only `ok`, `today` and `summary`. Calendar and e-mail never leave here.
- `lupin_post_signal` builds the Signal itself: the source is `agent:<client>`, there is no `data`
  and no `data_class`, and the kind must be on the allowlist below.
- Arguments and text are never logged; only the tool name, the client and the outcome are.
"""

from __future__ import annotations

import inspect
import logging
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.llm import SUPPORTED_EMOTIONS
from app.signals import Importance, Signal

logger = logging.getLogger(__name__)

SAY_MIN_LENGTH = 1
SAY_MAX_LENGTH = 280
SAY_RATE_LIMIT_SECONDS = 3.0
SIGNAL_SUMMARY_MAX_LENGTH = 200
CLIENT_NAME_MAX_LENGTH = 32
DEFAULT_CLIENT_NAME = "agent"

# The only kinds an agent may post. Everything else is refused before it reaches the bus.
AGENT_SIGNAL_KINDS: tuple[str, ...] = (
    "claude_code_needs_user",
    "build_failed",
    "build_finished",
    "agent_note",
)
AGENT_SIGNAL_IMPORTANCE: dict[str, Importance] = {
    "low": Importance.LOW,
    "normal": Importance.NORMAL,
    "important": Importance.IMPORTANT,
}

# Keys of the Today summary that may leave this module.
_TODAY_SUMMARY_KEYS: tuple[str, ...] = ("headline", "top", "warnings")

_SPACE_CONTROLS = frozenset("\t\n\r\x0b\x0c")


class AgentRequestError(Exception):
    """A refused request. The message is short and safe to show to the agent."""


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    risk: str  # "read" | "write"
    input_schema: dict  # JSON Schema object


def _clean_text(value: str) -> str:
    """Turn line breaks and tabs into spaces, drop other control characters, strip the ends."""
    value = "".join(" " if ch in _SPACE_CONTROLS else ch for ch in value)
    value = "".join(ch for ch in value if unicodedata.category(ch) != "Cc")
    return value.strip()


def safe_client_name(raw: str | None) -> str:
    """Lowercase the client name and keep only [a-z0-9_.-], at most 32 characters."""
    if not raw:
        return DEFAULT_CLIENT_NAME
    cleaned = re.sub(r"[^a-z0-9_.-]", "", str(raw).lower())[:CLIENT_NAME_MAX_LENGTH]
    return cleaned or DEFAULT_CLIENT_NAME


async def _settle(result: Any) -> Any:
    """Await a callback result when it is awaitable; pass plain values through."""
    if inspect.isawaitable(result):
        return await result
    return result


def _string_arg(arguments: dict, key: str, *, min_length: int, max_length: int) -> str:
    if key not in arguments or arguments[key] is None:
        raise AgentRequestError(f"{key} is required")
    value = arguments[key]
    if not isinstance(value, str):
        raise AgentRequestError(f"{key} must be a string")
    cleaned = _clean_text(value)
    if not min_length <= len(cleaned) <= max_length:
        raise AgentRequestError(f"{key} must be {min_length} to {max_length} characters")
    return cleaned


_SAY_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "minLength": SAY_MIN_LENGTH,
            "maxLength": SAY_MAX_LENGTH,
            "description": "The sentence Lupin says aloud (1 to 280 characters).",
        },
    },
    "required": ["text"],
    "additionalProperties": False,
}

_EXPRESSION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "enum": list(SUPPORTED_EMOTIONS),
            "description": "The Expression Lupin shows (case-insensitive).",
        },
    },
    "required": ["name"],
    "additionalProperties": False,
}

_TODAY_SCHEMA: dict = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}

_POST_SIGNAL_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "kind": {
            "type": "string",
            "enum": list(AGENT_SIGNAL_KINDS),
            "description": "What happened.",
        },
        "summary": {
            "type": "string",
            "minLength": 1,
            "maxLength": SIGNAL_SUMMARY_MAX_LENGTH,
            "description": "One short sentence (1 to 200 characters).",
        },
        "importance": {
            "type": "string",
            "enum": list(AGENT_SIGNAL_IMPORTANCE),
            "default": "normal",
        },
    },
    "required": ["kind", "summary"],
    "additionalProperties": False,
}

_TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="lupin_say",
        description=(
            "Make Lupin say a sentence aloud. Refused during focus time, and at most one "
            "sentence every 3 seconds."
        ),
        risk="write",
        input_schema=_SAY_SCHEMA,
    ),
    ToolSpec(
        name="lupin_show_expression",
        description="Change the Expression Lupin shows on his face.",
        risk="write",
        input_schema=_EXPRESSION_SCHEMA,
    ),
    ToolSpec(
        name="lupin_read_today",
        description="Read the Today summary: a headline, the top items and warnings.",
        risk="read",
        input_schema=_TODAY_SCHEMA,
    ),
    ToolSpec(
        name="lupin_post_signal",
        description=(
            "Post a Signal to Lupin's bus. Kinds: claude_code_needs_user, build_failed, "
            "build_finished, agent_note. The source is set to your client name."
        ),
        risk="write",
        input_schema=_POST_SIGNAL_SCHEMA,
    ),
)


class AgentRequests:
    """Validates and runs the four Agent Request tools against a SignalBus."""

    def __init__(self, signals: Any, today: Any = None, *, clock: Callable[[], float] = time.monotonic):
        self._signals = signals
        self._today = today
        self._clock = clock
        self._last_say: float | None = None

    def tool_specs(self) -> list[ToolSpec]:
        return list(_TOOL_SPECS)

    async def call(self, name: str, arguments: dict | None, client: str = "agent") -> dict:
        safe_client = safe_client_name(client)
        handler = self._handlers().get(name)
        if handler is None:
            logger.info("agent request tool=unknown client=%s ok=False", safe_client)
            raise AgentRequestError("unknown_tool")
        try:
            if arguments is None:
                arguments = {}
            if not isinstance(arguments, dict):
                raise AgentRequestError("arguments must be an object")
            result = await handler(arguments, safe_client)
        except AgentRequestError:
            logger.info("agent request tool=%s client=%s ok=False", name, safe_client)
            raise
        logger.info("agent request tool=%s client=%s ok=%s", name, safe_client, bool(result.get("ok")))
        return result

    # -- dispatch --------------------------------------------------------

    def _handlers(self) -> dict[str, Callable[[dict, str], Any]]:
        return {
            "lupin_say": self._say,
            "lupin_show_expression": self._show_expression,
            "lupin_read_today": self._read_today,
            "lupin_post_signal": self._post_signal,
        }

    @staticmethod
    def _check_keys(arguments: dict, schema: dict) -> None:
        allowed = set(schema["properties"])
        for key in arguments:
            if key not in allowed:
                raise AgentRequestError("unexpected argument")

    # -- tools -----------------------------------------------------------

    async def _say(self, arguments: dict, client: str) -> dict:
        self._check_keys(arguments, _SAY_SCHEMA)
        text = _string_arg(arguments, "text", min_length=SAY_MIN_LENGTH, max_length=SAY_MAX_LENGTH)

        now = self._clock()
        if self._last_say is not None and now - self._last_say < SAY_RATE_LIMIT_SECONDS:
            raise AgentRequestError("rate_limited")

        focus_active = getattr(self._signals, "focus_active", None)
        if focus_active is not None and await _settle(focus_active()):
            return {"ok": False, "reason": "focus"}

        speak = getattr(self._signals, "speak", None)
        if speak is None:
            return {"ok": False, "reason": "no_speaker"}

        # Reserve the slot before awaiting, so a concurrent call sees it.
        self._last_say = now
        said = await _settle(speak(text))
        if said is False:
            self._last_say = None
            return {"ok": False, "reason": "no_active_body"}
        return {"ok": True, "reason": "spoken"}

    async def _show_expression(self, arguments: dict, client: str) -> dict:
        self._check_keys(arguments, _EXPRESSION_SCHEMA)
        name = _string_arg(arguments, "name", min_length=1, max_length=32).lower()
        if name not in SUPPORTED_EMOTIONS:
            raise AgentRequestError("name must be one of: " + ", ".join(SUPPORTED_EMOTIONS))

        set_expression = getattr(self._signals, "set_expression", None)
        if set_expression is None:
            return {"ok": False, "reason": "no_expression"}
        result = await _settle(set_expression(name))
        if result is False:
            return {"ok": False, "reason": "no_active_body"}
        return {"ok": True, "reason": "shown", "expression": name}

    async def _read_today(self, arguments: dict, client: str) -> dict:
        self._check_keys(arguments, _TODAY_SCHEMA)
        if self._today is None:
            return {"ok": False, "reason": "today_unavailable"}
        result = await _settle(self._today.generate_today())
        if not isinstance(result, dict):
            return {"ok": False, "reason": "today_unavailable"}
        summary = result.get("summary")
        if isinstance(summary, dict):
            summary = {key: summary[key] for key in _TODAY_SUMMARY_KEYS if key in summary}
        return {"ok": bool(result.get("ok")), "today": result.get("today"), "summary": summary}

    async def _post_signal(self, arguments: dict, client: str) -> dict:
        self._check_keys(arguments, _POST_SIGNAL_SCHEMA)
        kind = arguments.get("kind")
        if not isinstance(kind, str) or kind not in AGENT_SIGNAL_KINDS:
            raise AgentRequestError("kind must be one of: " + ", ".join(AGENT_SIGNAL_KINDS))
        summary = _string_arg(
            arguments, "summary", min_length=1, max_length=SIGNAL_SUMMARY_MAX_LENGTH
        )
        importance_name = arguments.get("importance", "normal")
        if not isinstance(importance_name, str) or importance_name not in AGENT_SIGNAL_IMPORTANCE:
            raise AgentRequestError("importance must be one of: " + ", ".join(AGENT_SIGNAL_IMPORTANCE))

        signal = Signal(
            kind=kind,
            source=f"agent:{client}",
            importance=AGENT_SIGNAL_IMPORTANCE[importance_name],
            summary=summary,
        )
        result = await _settle(self._signals.emit(signal))
        return {
            "ok": True,
            "spoke": result.spoke,
            "expression": result.expression,
            "reason": result.reason,
        }
