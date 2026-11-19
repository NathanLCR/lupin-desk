"""Brain-side Signals: one event bus for things that happen outside the chat.

A signal source (a timer, a build watcher, Claude Code, a calendar reader...) builds a `Signal`
and calls `SignalBus.emit`. The bus then, in order:

1. publishes it to the widget topics `signals` and `signal:<kind>` on the `DeviceHub`;
2. calls the generic listeners (the MCP server subscribes this way);
3. lets Lupin react: speak (only for allowed kinds, rate limited, quieter during focus) and
   set an expression.

Every step is isolated: a failure is logged (exception type only, never the data) and the next
step still runs. All policy is data at the top of this module, not scattered ifs.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import itertools
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any

from app import speech

logger = logging.getLogger(__name__)


class Importance(IntEnum):
    LOW = 0
    NORMAL = 1
    IMPORTANT = 2


# Signals whose data carries these contents must not reach an LLM without the matching consent.
SENSITIVE_DATA_CLASSES = frozenset({"calendar", "email", "files"})


# ---------------------------------------------------------------------------
# Policy (data only)
# ---------------------------------------------------------------------------

# Only these kinds may make Lupin speak unprompted, whatever their importance says.
SPEAKING_KINDS = frozenset(
    {"claude_code_needs_user", "build_failed", "timer_done", "habit_due", "meeting_soon"}
)

# During focus (Pomodoro) only these kinds speak.
FOCUS_SPEAKING_KINDS = frozenset({"claude_code_needs_user"})

# Minimum seconds between two spoken signals of the same kind.
DEFAULT_RATE_LIMIT_SECONDS = 300.0
RATE_LIMIT_SECONDS: dict[str, float] = {
    "claude_code_needs_user": 60.0,
    "build_failed": 120.0,
    "timer_done": 30.0,
    "habit_due": 600.0,
    "meeting_soon": 300.0,
}

# Expression Lupin shows for a kind. Every name must be a known expression.
KIND_EXPRESSIONS: dict[str, str] = {
    "claude_code_needs_user": "curious",
    "build_failed": "sad",
    "timer_done": "happy",
    "habit_due": "curious",
    "meeting_soon": "surprised",
    "mac_heavy_load": "dizzy",
}

# Fallback expression by importance, used when the kind has no expression of its own.
IMPORTANCE_EXPRESSIONS: dict[Importance, str] = {
    Importance.NORMAL: "curious",
}

# Upper bounds (seconds) so a slow hub send, listener or TTS never blocks the caller for long.
PUBLISH_TIMEOUT_SECONDS = 5.0
LISTENER_TIMEOUT_SECONDS = 5.0
SPEAK_TIMEOUT_SECONDS = 20.0

SIGNALS_TOPIC = "signals"
SIGNAL_KIND_TOPIC_PREFIX = "signal:"
_TOPIC_MAX_LENGTH = 64
_KIND_RE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Signal:
    kind: str
    source: str
    importance: Importance = Importance.NORMAL
    summary: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    # "calendar" | "email" | "files" when `data` carries such contents.
    data_class: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "importance": self.importance.name.lower(),
            "summary": self.summary,
            "data": dict(self.data),
        }


@dataclass(frozen=True)
class EmitResult:
    published: int
    spoke: bool
    expression: str | None
    reason: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _settle(result: Any) -> Any:
    """Await a callback result when the callback is async; pass plain values through."""
    if inspect.isawaitable(result):
        return await result
    return result


def _topics_for(kind: str) -> list[str]:
    topics = [SIGNALS_TOPIC]
    kind_topic = SIGNAL_KIND_TOPIC_PREFIX + kind
    if _KIND_RE.fullmatch(kind) and len(kind_topic) <= _TOPIC_MAX_LENGTH:
        topics.append(kind_topic)
    return topics


def _minimal_view(signal: Signal) -> dict[str, str]:
    importance = getattr(signal, "importance", Importance.NORMAL)
    return {
        "kind": str(getattr(signal, "kind", "")),
        "source": str(getattr(signal, "source", "")),
        "importance": getattr(importance, "name", "normal").lower(),
    }


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------


class SignalBus:
    """Publishes signals to widgets, notifies listeners, and lets Lupin react."""

    def __init__(
        self,
        hub: Any = None,
        *,
        speak: Callable[[str], Any] | None = None,
        set_expression: Callable[[str], Any] | None = None,
        focus_active: Callable[[], bool] | None = None,
        consent: Callable[[], dict[str, bool]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.hub = hub
        self.speak = speak
        self.set_expression = set_expression
        self.focus_active = focus_active
        self.consent = consent
        self._clock = clock
        self._listeners: list[Callable[[Signal], Any]] = []
        self._last_spoken: dict[str, float] = {}

    def add_listener(self, callback: Callable[[Signal], Any]) -> Callable[[], None]:
        """Subscribe to every emitted signal; return a function that removes the subscription."""
        self._listeners.append(callback)

        def remove() -> None:
            if callback in self._listeners:
                self._listeners.remove(callback)

        return remove

    async def emit(self, signal: Signal) -> EmitResult:
        if not signal.kind or not signal.source:
            raise ValueError("A signal needs a non-empty kind and source.")
        published = await self._publish(signal)
        await self._notify_listeners(signal)
        return await self._react(signal, published)

    def llm_view(self, signal: Signal) -> dict[str, Any]:
        """What an LLM may see of a signal. Sensitive contents need their consent; never raises."""
        try:
            if signal.data_class in SENSITIVE_DATA_CLASSES and not self._consent_allows(
                signal.data_class
            ):
                return _minimal_view(signal)
            return signal.to_dict()
        except Exception as exc:
            logger.warning("Signal LLM view fell back to the minimal view (%s).", type(exc).__name__)
            return _minimal_view(signal)

    # -- steps -----------------------------------------------------------

    async def _publish(self, signal: Signal) -> int:
        if self.hub is None:
            return 0
        payload = signal.to_dict()
        delivered_total = 0
        for topic in _topics_for(signal.kind):
            try:
                delivered_total += int(
                    await asyncio.wait_for(self.hub.publish(topic, payload), PUBLISH_TIMEOUT_SECONDS)
                )
            except Exception as exc:
                logger.warning("Signal %s was not published (%s).", topic, type(exc).__name__)
        return delivered_total

    async def _notify_listeners(self, signal: Signal) -> None:
        for callback in list(self._listeners):
            try:
                await asyncio.wait_for(_settle(callback(signal)), LISTENER_TIMEOUT_SECONDS)
            except Exception as exc:
                logger.warning("A signal listener failed (%s).", type(exc).__name__)

    async def _react(self, signal: Signal, published: int) -> EmitResult:
        kind = signal.kind
        in_focus = self._in_focus()
        speaking_allowed = FOCUS_SPEAKING_KINDS if in_focus else SPEAKING_KINDS

        if in_focus and kind not in FOCUS_SPEAKING_KINDS:
            return EmitResult(published, False, None, "focus")

        spoke = False
        if kind not in speaking_allowed:
            reason = "expression_only"
        else:
            text = signal.summary.strip() or getattr(speech, "SIGNAL_LINES", {}).get(kind, "")
            if not text:
                reason = "no_text"
            elif not self._rate_limit_allows(kind):
                reason = "rate_limited"
            else:
                if self.speak is None:
                    reason = "no_speaker"
                else:
                    # Reserve the rate slot before awaiting, so a concurrent emit of the same
                    # kind sees it; give it back if nothing was actually said.
                    previous = self._last_spoken.get(kind)
                    self._last_spoken[kind] = self._clock()
                    outcome = await self._speak(text)
                    if outcome == "spoken":
                        spoke = True
                    else:
                        if previous is None:
                            self._last_spoken.pop(kind, None)
                        else:
                            self._last_spoken[kind] = previous
                    reason = outcome

        expression = KIND_EXPRESSIONS.get(kind) or IMPORTANCE_EXPRESSIONS.get(signal.importance)
        if expression is None and reason == "expression_only":
            reason = "silent"

        expression_set: str | None = None
        if (spoke or (not in_focus and reason != "rate_limited")) and expression is not None:
            if await self._set_expression(expression):
                expression_set = expression
        return EmitResult(published, spoke, expression_set, reason)

    def _in_focus(self) -> bool:
        if self.focus_active is None:
            return False
        try:
            return bool(self.focus_active())
        except Exception as exc:
            logger.warning("Focus check failed (%s); treating as not in focus.", type(exc).__name__)
            return False

    def _rate_limit_allows(self, kind: str) -> bool:
        last = self._last_spoken.get(kind)
        if last is None:
            return True
        limit = RATE_LIMIT_SECONDS.get(kind, DEFAULT_RATE_LIMIT_SECONDS)
        return self._clock() - last >= limit

    async def _speak(self, text: str) -> str:
        """Return "spoken", "no_active_body" (the callback returned False) or "speak_failed"."""
        if self.speak is None:
            return "no_speaker"
        try:
            result = await asyncio.wait_for(_settle(self.speak(text)), SPEAK_TIMEOUT_SECONDS)
        except Exception as exc:
            logger.warning("Lupin could not speak a signal (%s).", type(exc).__name__)
            return "speak_failed"
        return "no_active_body" if result is False else "spoken"

    async def _set_expression(self, name: str) -> bool:
        if self.set_expression is None:
            return False
        try:
            result = await asyncio.wait_for(_settle(self.set_expression(name)), SPEAK_TIMEOUT_SECONDS)
            return result is not False
        except Exception as exc:
            logger.warning("Lupin could not change expression (%s).", type(exc).__name__)
            return False

    def _consent_allows(self, data_class: str) -> bool:
        # "files" has no consent switch, so it is never allowed to reach an LLM.
        if data_class == "files" or self.consent is None:
            return False
        try:
            return self.consent()[data_class] is True
        except Exception as exc:
            logger.warning("Consent check failed (%s).", type(exc).__name__)
            return False


# ---------------------------------------------------------------------------
# Lupin's voice for unprompted signals
# ---------------------------------------------------------------------------


class ActiveBodySpeaker:
    """Callbacks that make Lupin speak or change Expression on the Active Body.

    `get_active_body()` returns the hub's active entry (a dict with `send`, `wants_audio`, `body`)
    or None. Text goes as a `notice` (kind `signal`); the voice goes as `audio` chunks only when
    that Body asked for server audio and TTS is available. Nothing is sent when no Body is active.
    """

    def __init__(
        self,
        get_active_body: Callable[[], dict[str, Any] | None],
        tts: Any = None,
        voice: Callable[[], str] | None = None,
        chunk_bytes: int = 24 * 1024,
    ) -> None:
        self._get_active_body = get_active_body
        self._tts = tts
        self._voice = voice
        self._chunk_bytes = chunk_bytes
        self._audio_ids = itertools.count(1)

    async def speak(self, text: str) -> bool:
        """Say `text` on the Active Body; False when there is none (nothing was said)."""
        entry = self._get_active_body()
        if entry is None:
            return False
        await entry["send"]({"type": "notice", "kind": "signal", "text": text})
        if not entry.get("wants_audio") or self._tts is None:
            return True
        try:
            if not self._tts.is_available():
                return True
            audio, _mime = await self._tts.synthesize_async(
                text=text, voice=self._voice() if self._voice else None, output_format="m4a"
            )
        except Exception as exc:
            logger.warning("TTS failed for a signal (%s); audio skipped.", type(exc).__name__)
            return True
        # A string key that cannot collide with the integer sentence indexes of a chat turn.
        sentence_key = f"signal:{next(self._audio_ids)}"
        total = max(1, -(-len(audio) // self._chunk_bytes))
        for seq in range(total):
            chunk = audio[seq * self._chunk_bytes : (seq + 1) * self._chunk_bytes]
            await entry["send"](
                {
                    "type": "audio",
                    "sentence": sentence_key,
                    "signal": True,
                    "seq": seq,
                    "last": seq == total - 1,
                    "mime": "audio/mp4",
                    "data": base64.b64encode(chunk).decode("ascii"),
                }
            )
        return True

    async def set_expression(self, name: str) -> bool:
        entry = self._get_active_body()
        if entry is None:
            return False
        await entry["send"]({"type": "emotion", "emotion": name})
        return True
