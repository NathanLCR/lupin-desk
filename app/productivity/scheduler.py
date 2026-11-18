"""Habit reminders: turns due habits into `habit_due` Signals on the SignalBus.

The scheduler polls the store every `interval` seconds. Each due habit becomes one Signal; the
habit is then marked notified for today so it is not repeated until the next day. A habit whose
emit raised is left unmarked, so the next tick retries it.

Habit names are never logged; only exception type names are.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from app.signals import Importance, Signal

logger = logging.getLogger(__name__)

HABIT_DUE_KIND = "habit_due"
HABIT_DUE_SOURCE = "habits"
DEFAULT_INTERVAL_SECONDS = 30.0


def _default_line(name: str) -> str:
    """Spoken summary for a due habit; resolved at call time so speech can be added later."""
    try:
        from app import speech

        builder = getattr(speech, "habit_due_line", None)
    except Exception as exc:
        logger.warning("Habit speech unavailable (%s).", type(exc).__name__)
        builder = None
    if builder is None:
        return f"Habit due: {name}"
    return builder(name)


class HabitScheduler:
    """Polls the productivity store and emits `habit_due` Signals for due habits."""

    def __init__(
        self,
        store: Any,
        get_signals: Callable[[], Any],
        *,
        clock: Callable[[], datetime] = datetime.now,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        line: Callable[[str], str] | None = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    ) -> None:
        self._store = store
        self._get_signals = get_signals
        self._clock = clock
        self._interval = interval
        self._line = line if line is not None else _default_line
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    async def tick(self) -> int:
        """Emit a signal for each habit due now; return how many were emitted."""
        bus = self._get_signals()
        if bus is None:
            return 0

        now = self._clock()
        emitted = 0
        for habit in self._store.due_habits(now):
            try:
                signal = Signal(
                    kind=HABIT_DUE_KIND,
                    source=HABIT_DUE_SOURCE,
                    importance=Importance.IMPORTANT,
                    summary=self._line(habit["name"]),
                    data={
                        "id": habit["id"],
                        "name": habit["name"],
                        "streak": habit["streak"],
                    },
                )
                await bus.emit(signal)
            except Exception as exc:
                logger.warning("Habit reminder was not emitted (%s).", type(exc).__name__)
                continue
            # Rate-limited or silent results still count as notified: the reminder for today
            # was handled, and repeating it on the next tick would only be noise.
            self._store.mark_habit_notified(habit["id"], now.date().isoformat())
            emitted += 1
        return emitted

    def start(self) -> None:
        """Start the polling loop in the running event loop. Idempotent."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the polling loop and wait for it to end. Safe to call repeatedly or unstarted."""
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.warning("Habit scheduler tick failed (%s).", type(exc).__name__)
            await self._sleep(self._interval)
