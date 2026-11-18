"""Everyday Panel widgets: media keys, timers, Pomodoro end, today's calendar and meeting reminders.

Devices only ever name an action ID (``media.next``, ``timers.start``...). Each Mac action maps to
one command of the closed whitelist in ``app.mac_control``; no client ever sends a command.

Timers live in memory and are tracked by absolute end time from the injected clock. One background
loop checks them every ``interval`` seconds, along with the Pomodoro end and upcoming meetings.
Calendar data is read-only and reaches the Signals bus only with ``data_class="calendar"``, so an
LLM without Data Consent never sees a meeting title.

Every failure in the loop is caught and logged by exception type name only, so the loop never dies.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import logging
import math
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI

from app.signals import Importance, Signal

logger = logging.getLogger(__name__)

MAX_ACTIVE_TIMERS = 20
MAX_TIMER_SECONDS = 86400
MAX_TIMER_LABEL_LENGTH = 40
MEETING_WINDOW_SECONDS = 600
CALENDAR_READ_INTERVAL_SECONDS = 60.0
DEFAULT_INTERVAL_SECONDS = 5.0
DEFAULT_POMODORO_MINUTES = 25

TIMERS_TOPIC = "timers"
TIMER_DONE_KIND = "timer_done"
MEETING_SOON_KIND = "meeting_soon"

# Media and Pomodoro action IDs and the whitelisted Mac command each one runs.
MAC_ACTIONS: dict[str, str] = {
    "media.play_pause": "play_pause",
    "media.next": "next_track",
    "media.previous": "prev_track",
    "pomodoro.start": "pomodoro_start",
    "pomodoro.stop": "pomodoro_stop",
}


def _validate_seconds(value: Any) -> int:
    # type() rejects bool, which is a subclass of int, as well as floats and strings.
    if type(value) is not int:
        raise ValueError("seconds must be an integer")
    if not 1 <= value <= MAX_TIMER_SECONDS:
        raise ValueError("seconds out of range")
    return value


def _validate_label(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError("label must be a string")
    label = value.strip()
    if len(label) > MAX_TIMER_LABEL_LENGTH:
        raise ValueError("label too long")
    return label


class TimerService:
    """In-memory countdown timers keyed by absolute end time (epoch seconds from ``clock``)."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._timers: dict[str, dict[str, Any]] = {}

    def start(self, args: dict[str, Any]) -> dict[str, Any]:
        seconds = _validate_seconds(args.get("seconds"))
        label = _validate_label(args.get("label"))
        if len(self._timers) >= MAX_ACTIVE_TIMERS:
            raise ValueError("too many active timers")
        timer_id = uuid.uuid4().hex[:12]
        self._timers[timer_id] = {
            "id": timer_id,
            "label": label,
            "seconds": seconds,
            "end": self._clock() + seconds,
        }
        return {"id": timer_id, "label": label, "seconds": seconds}

    def cancel(self, args: dict[str, Any]) -> dict[str, Any]:
        timer_id = args.get("id")
        if not isinstance(timer_id, str) or timer_id not in self._timers:
            raise ValueError("unknown timer")
        del self._timers[timer_id]
        return {"id": timer_id, "cancelled": True}

    def payload(self) -> dict[str, Any]:
        now = self._clock()
        return {
            "timers": [
                {
                    "id": timer["id"],
                    "label": timer["label"],
                    "seconds": timer["seconds"],
                    "remaining": max(0, math.ceil(timer["end"] - now)),
                }
                for timer in self._timers.values()
            ]
        }

    def pop_due(self, now: float) -> list[dict[str, Any]]:
        due = [timer for timer in self._timers.values() if timer["end"] <= now]
        for timer in due:
            del self._timers[timer["id"]]
        return due


def _parse_hhmm(value: Any) -> tuple[int, int] | None:
    if not isinstance(value, str) or len(value) != 5 or value[2] != ":":
        return None
    try:
        hour, minute = int(value[:2]), int(value[3:])
    except ValueError:
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


class Everyday:
    """Owns the timers, the calendar reads and the background loop."""

    def __init__(
        self,
        fastapi_app: FastAPI,
        mac: Any,
        *,
        calendar_reader: Callable[[], Any] | None,
        clock: Callable[[], float],
        interval: float,
    ) -> None:
        self._app = fastapi_app
        self._mac = mac
        self._calendar_reader = calendar_reader
        self._clock = clock
        self._interval = interval
        self.timers = TimerService(clock)
        self._task: asyncio.Task[None] | None = None
        self._events: list[dict[str, Any]] = []
        self._last_calendar_read: float | None = None
        self._announced_date: str | None = None
        self._announced: set[str] = set()

    # -- lifecycle -------------------------------------------------------

    def start(self) -> None:
        """Start the background loop in the running event loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the background loop and wait for it to end. Safe to call repeatedly."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        while True:
            await self.tick()
            await asyncio.sleep(self._interval)

    # -- shared helpers --------------------------------------------------

    def _signals(self) -> Any:
        return getattr(self._app.state, "signals", None)

    async def _emit(self, signal: Signal) -> None:
        bus = self._signals()
        if bus is None:
            return
        try:
            await bus.emit(signal)
        except Exception as exc:
            logger.warning("Everyday signal was not emitted (%s).", type(exc).__name__)

    async def publish_timers(self) -> None:
        hub = getattr(self._app.state, "device_hub", None)
        if hub is None:
            return
        try:
            await hub.publish(TIMERS_TOPIC, self.timers.payload())
        except Exception as exc:
            logger.warning("Timers were not published (%s).", type(exc).__name__)

    async def read_calendar(self) -> list[dict[str, Any]] | None:
        """Read today's events (read-only). None when the calendar cannot be read."""
        reader = self._calendar_reader
        if reader is None:
            reader = self._mac.read_today_calendar
        result = await asyncio.to_thread(reader)
        if inspect.isawaitable(result):
            result = await result
        return result

    # -- tick ------------------------------------------------------------

    async def tick(self) -> None:
        """Run one pass: due timers, Pomodoro end, meetings soon. Never raises."""
        now = self._clock()
        try:
            await self._check_timers(now)
        except Exception as exc:
            logger.warning("Timer check failed (%s).", type(exc).__name__)
        try:
            await self._check_pomodoro(now)
        except Exception as exc:
            logger.warning("Pomodoro check failed (%s).", type(exc).__name__)
        try:
            await self._check_meetings(now)
        except Exception as exc:
            logger.warning("Meeting check failed (%s).", type(exc).__name__)

    async def _check_timers(self, now: float) -> None:
        due = self.timers.pop_due(now)
        if not due:
            return
        for timer in due:
            await self._emit(
                Signal(
                    kind=TIMER_DONE_KIND,
                    source="timers",
                    importance=Importance.IMPORTANT,
                    summary="",
                    data={"id": timer["id"], "label": timer["label"]},
                )
            )
        await self.publish_timers()

    async def _check_pomodoro(self, now: float) -> None:
        state_getter = getattr(self._mac, "pomodoro_state", None)
        if state_getter is None:
            return
        state = state_getter()
        if not state.get("active") or not state.get("started_at"):
            return
        started = datetime.fromisoformat(state["started_at"])
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        duration = int(state.get("duration_minutes") or DEFAULT_POMODORO_MINUTES)
        if started.timestamp() + duration * 60 > now:
            return
        result = await asyncio.to_thread(self._mac.execute_mac_command, "pomodoro_stop")
        if not result or not result.get("ok"):
            logger.warning("Pomodoro could not be stopped at its end; retrying next tick.")
            return
        await self._emit(
            Signal(
                kind=TIMER_DONE_KIND,
                source="pomodoro",
                importance=Importance.IMPORTANT,
                summary="",
                data={"id": "pomodoro", "label": "Pomodoro"},
            )
        )

    async def _check_meetings(self, now: float) -> None:
        if (
            self._last_calendar_read is None
            or now - self._last_calendar_read >= CALENDAR_READ_INTERVAL_SECONDS
        ):
            self._last_calendar_read = now
            try:
                events = await self.read_calendar()
            except Exception as exc:
                logger.warning("Calendar read failed for reminders (%s).", type(exc).__name__)
                events = None
            self._events = events or []

        local_now = datetime.fromtimestamp(now)
        today = local_now.date().isoformat()
        if today != self._announced_date:
            self._announced_date = today
            self._announced = set()

        for event in self._events:
            if event.get("all_day"):
                continue
            parsed = _parse_hhmm(event.get("start"))
            if parsed is None:
                continue
            title = str(event.get("title") or "")
            start = event["start"]
            event_at = local_now.replace(hour=parsed[0], minute=parsed[1], second=0, microsecond=0)
            delta = (event_at - local_now).total_seconds()
            if delta < 0 or delta > MEETING_WINDOW_SECONDS:
                continue
            key = f"{today} {start} {title}"
            if key in self._announced:
                continue
            await self._emit(
                Signal(
                    kind=MEETING_SOON_KIND,
                    source="calendar",
                    importance=Importance.IMPORTANT,
                    summary="",
                    data={"title": title, "start": start},
                    data_class="calendar",
                )
            )
            self._announced.add(key)


def register(
    fastapi_app: FastAPI,
    mac: Any,
    *,
    calendar_reader: Callable[[], Any] | None = None,
    clock: Callable[[], float] = time.time,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> Everyday:
    """Wire the everyday actions, the panel routes and the background loop into the app.

    The device hub, the signals and the action registry are looked up on each call, so they may
    be set on app.state before or after this runs.
    """
    everyday = Everyday(
        fastapi_app,
        mac,
        calendar_reader=calendar_reader,
        clock=clock,
        interval=interval,
    )

    actions = getattr(fastapi_app.state, "actions", None)
    if actions is not None:
        for action_id, command in MAC_ACTIONS.items():
            actions.register(action_id, _mac_handler(mac, command), f"Mac: {command}")

        async def timers_start(args: dict[str, Any]) -> dict[str, Any]:
            result = everyday.timers.start(args)
            await everyday.publish_timers()
            return result

        async def timers_cancel(args: dict[str, Any]) -> dict[str, Any]:
            result = everyday.timers.cancel(args)
            await everyday.publish_timers()
            return result

        actions.register("timers.start", timers_start, "Start a countdown timer")
        actions.register("timers.cancel", timers_cancel, "Cancel a countdown timer")

    @fastapi_app.get("/api/panel/timers")
    async def panel_timers() -> dict[str, Any]:
        return everyday.timers.payload()

    @fastapi_app.get("/api/panel/calendar")
    async def panel_calendar() -> dict[str, Any]:
        try:
            events = await everyday.read_calendar()
        except Exception as exc:
            logger.warning("Calendar read failed (%s).", type(exc).__name__)
            events = None
        if events is None:
            return {"ok": False, "events": []}
        return {
            "ok": True,
            "events": [
                {"start": event["start"], "title": event["title"], "all_day": event["all_day"]}
                for event in events
            ],
        }

    fastapi_app.state.everyday = everyday
    return everyday


def _mac_handler(mac: Any, command: str) -> Callable[[dict[str, Any]], Any]:
    async def handler(_args: dict[str, Any]) -> dict[str, Any]:
        result = await asyncio.to_thread(mac.execute_mac_command, command)
        if not result or not result.get("ok"):
            raise ValueError("Mac command failed.")
        return result

    return handler
