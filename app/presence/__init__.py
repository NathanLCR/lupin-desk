"""Presence (Lupin 04): Lupin on the desk while the user works.

- Break reminders from continuous work (HIDIdleTime), through Signals (`break_reminder`).
- Time of day drives Energy; Now Playing nudges the tone; touch snoozes the reminder and
  makes Lupin happy. None of this makes Lupin comment on what the user is doing.
- The Mac's front app (name and window title) reaches the LLM only with the front app Data
  Consent. It is never stored or logged.

`register(app, memory, mac, ...)` sets `app.state.presence`; the Brain calls
`presence.turn_context()` per turn, `presence.on_touch()` on a touch and
`presence.handle_voice("break", target)` for `[action:break:...]` tags.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel

from app import speech
from app.consent import FrontAppConsent, build_front_app_context
from app.memory import _derive_mood_label
from app.presence.breaks import (
    DEFAULT_INTERVAL_MINUTES,
    MAX_INTERVAL_MINUTES,
    MIN_INTERVAL_MINUTES,
    BreakTracker,
    clamp_interval,
)
from app.presence.tone import effective_energy, idle_expression, music_tone
from app.signals import Importance, Signal

logger = logging.getLogger(__name__)

POLL_SECONDS = 30.0
NOW_PLAYING_TTL_SECONDS = 60.0
SETTINGS_META_KEY = "presence_settings"
BREAK_SIGNAL_KIND = "break_reminder"
_UNSPOKEN = frozenset({"no_active_body", "speak_failed", "no_speaker"})


def _say(name: str, default: str, *args: Any) -> str:
    """A speech-table string (en and pt-BR), with an English fallback until the table has it."""
    value = getattr(speech, name, None)
    if value is None:
        return default.format(*args)
    return str(value(*args)) if callable(value) else str(value)


class PresenceSettingsRequest(BaseModel):
    break_enabled: bool | None = None
    break_minutes: int | None = None
    front_app: bool | None = None


class Presence:
    def __init__(
        self,
        memory: Any,
        mac: Any,
        signals: Callable[[], Any],
        consent: FrontAppConsent,
        *,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = datetime.now,
        poll_seconds: float = POLL_SECONDS,
    ) -> None:
        self._memory = memory
        self._mac = mac
        self._signals = signals
        self.consent = consent
        self._clock = clock
        self._now = now
        self._poll_seconds = poll_seconds
        self._task: asyncio.Task[None] | None = None
        self._playing: tuple[float, dict[str, Any] | None] | None = None
        self.tracker = BreakTracker()
        self._load_settings()

    # -- settings ----------------------------------------------------------

    def _load_settings(self) -> None:
        try:
            data = json.loads(self._memory.get_meta(SETTINGS_META_KEY) or "{}")
        except (ValueError, json.JSONDecodeError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        minutes = data.get("break_minutes")
        self.tracker.interval_minutes = (
            clamp_interval(minutes) if isinstance(minutes, (int, float)) and not isinstance(minutes, bool)
            else DEFAULT_INTERVAL_MINUTES
        )
        self.tracker.enabled = data.get("break_enabled") is not False

    def _save_settings(self) -> None:
        payload = {"break_enabled": self.tracker.enabled, "break_minutes": self.tracker.interval_minutes}
        self._memory.set_meta(SETTINGS_META_KEY, json.dumps(payload))

    def settings(self) -> dict[str, Any]:
        return {
            "break_enabled": self.tracker.enabled,
            "break_minutes": self.tracker.interval_minutes,
            "break_min": MIN_INTERVAL_MINUTES,
            "break_max": MAX_INTERVAL_MINUTES,
            "front_app": self.consent.get(),
            "front_app_local": self.consent.is_local(),
        }

    def update_settings(
        self, break_enabled: bool | None = None, break_minutes: int | None = None, front_app: bool | None = None
    ) -> dict[str, Any]:
        if break_enabled is not None:
            self.tracker.enabled = bool(break_enabled)
        if break_minutes is not None:
            self.tracker.set_interval(break_minutes)
        if break_enabled is not None or break_minutes is not None:
            self._save_settings()
        if front_app is not None:
            self.consent.update(front_app)
        return self.settings()

    # -- break reminders ---------------------------------------------------

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

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
                logger.warning("Presence tick failed (%s).", type(exc).__name__)
            await asyncio.sleep(self._poll_seconds)

    async def tick(self) -> bool:
        """Sample the idle time once; emit a break reminder when one is due. True if emitted."""
        idle = await asyncio.to_thread(self._mac.read_idle_seconds)
        pomodoro = bool(getattr(self._mac, "pomodoro_active", lambda: False)())
        now = self._clock()
        if not self.tracker.update(now, idle, pomodoro):
            return False
        bus = self._signals()
        if bus is None:
            return False
        minutes = max(1, self.tracker.work_minutes(now))
        text = _say(
            "break_reminder",
            "You've been at it for about {0} minutes. How about a short break?",
            minutes,
        )
        result = await bus.emit(
            Signal(
                kind=BREAK_SIGNAL_KIND,
                source="presence",
                importance=Importance.NORMAL,
                summary=text,
                data={"minutes": minutes},
            )
        )
        if result.reason in _UNSPOKEN:
            return False  # nobody heard it: try again on the next sample
        self.tracker.mark_reminded(now)
        return bool(result.spoke)

    # -- touch and voice ---------------------------------------------------

    def on_touch(self, kind: str = "pet") -> str | None:
        """A touch snoozes break reminders for 10 minutes. Returns the Expression to show.

        Petting is happy; the affinity change itself is `MemoryStore.record_pet`.
        """
        self.tracker.snooze(self._clock())
        return "happy" if kind == "pet" else None

    async def handle_voice(self, kind: str, target: str) -> dict[str, Any]:
        """`[action:break:every:<minutes>]`, `[action:break:off]`, `[action:break:on]`, `[action:break:snooze]`."""
        verb, _, arg = str(target or "").partition(":")
        verb = verb.strip().lower()
        arg = arg.strip()
        spoken = ""
        ok = True
        if verb == "every":
            try:
                minutes = self.tracker.set_interval(float(arg))
            except ValueError:
                ok, spoken = False, _say("break_interval_invalid", "Sorry, I didn't get the interval.")
            else:
                self.tracker.enabled = True
                self._save_settings()
                spoken = _say("break_interval_set", "Okay, I'll remind you about breaks every {0} minutes.", minutes)
        elif verb in ("off", "on"):
            self.tracker.enabled = verb == "on"
            self._save_settings()
            spoken = (
                _say("break_reminders_on", "Okay, break reminders are back on.")
                if verb == "on"
                else _say("break_reminders_off", "Okay, no more break reminders.")
            )
        elif verb == "snooze":
            self.tracker.snooze(self._clock())
            spoken = _say("break_snoozed", "Okay, I'll leave you alone for ten minutes.")
        else:
            ok, spoken = False, _say("break_interval_invalid", "Sorry, I didn't get the interval.")
        return {"ok": ok, "spoken": spoken, "kind": "break", "verb": verb}

    # -- tone, Energy and the per-turn context -----------------------------

    def idle_expression(self) -> str | None:
        return idle_expression(self._now().hour)

    def companion_line(self) -> str:
        """The companion prompt line with Energy driven by the time of day."""
        state = self._memory.get_companion_state()
        energy = effective_energy(float(state["energy"]), self._now().hour)
        mood = _derive_mood_label(float(state["pleasure"]), float(state["arousal"]), energy)
        return speech.companion_prompt_line(mood, energy, float(state["affinity"]))

    async def now_playing_tone(self) -> str | None:
        cached = self._playing
        now = self._clock()
        if cached is None or now - cached[0] > NOW_PLAYING_TTL_SECONDS:
            try:
                playing = await asyncio.to_thread(self._mac.now_playing)
            except Exception as exc:
                logger.warning("Now Playing read failed (%s).", type(exc).__name__)
                playing = None
            self._playing = cached = (now, playing)
        return music_tone(cached[1])

    async def front_app(self) -> dict[str, str] | None:
        """The front app, for use on the Mac only (never log or store it)."""
        try:
            return await asyncio.to_thread(self._mac.front_app)
        except Exception as exc:
            logger.warning("Front app read failed (%s).", type(exc).__name__)
            return None

    async def turn_context(self) -> str:
        """Ephemeral per-turn context: music tone and, only with the front app consent, the front app.

        Without the consent the front app is not even read. Never stored, never logged.
        """
        parts: list[str] = []
        tone = await self.now_playing_tone()
        if tone is not None:
            parts.append(_say(
                "presence_music_line",
                "Music is playing in the background and it feels {0}: let your tone follow it a little. "
                "Never mention the music unless asked.",
                tone,
            ))
        if self.consent.get():
            line = build_front_app_context(True, await self.front_app())
            if line:
                parts.append(line)
        return "\n\n".join(parts)


def register(
    fastapi_app: FastAPI,
    memory: Any,
    mac: Any,
    signature: Callable[[], tuple[str, str]],
    require_mac_client: Callable[[Request, str], None],
    *,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime] = datetime.now,
    poll_seconds: float = POLL_SECONDS,
) -> Presence:
    """Wire Presence into the app: `app.state.presence` plus `GET/PUT /api/presence`.

    Reading the settings is open to LAN clients; changing them (interval, front app consent)
    is Mac-only. The Signals bus is looked up when a reminder is due.
    """
    presence = Presence(
        memory,
        mac,
        lambda: getattr(fastapi_app.state, "signals", None),
        FrontAppConsent(memory, signature),
        clock=clock,
        now=now,
        poll_seconds=poll_seconds,
    )

    @fastapi_app.get("/api/presence")
    async def get_presence() -> dict[str, Any]:
        return presence.settings()

    @fastapi_app.put("/api/presence")
    async def put_presence(request: Request, body: PresenceSettingsRequest) -> dict[str, Any]:
        require_mac_client(request, "Presence settings can only be changed on the Mac.")
        if body.break_minutes is not None and body.break_minutes <= 0:
            raise HTTPException(status_code=422, detail="break_minutes must be positive.")
        return presence.update_settings(body.break_enabled, body.break_minutes, body.front_app)

    fastapi_app.state.presence = presence
    return presence
