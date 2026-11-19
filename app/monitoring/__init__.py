"""Mac monitoring (P08): publishes CPU, RAM, disks, network, ping and top processes.

The collector only runs while at least one connected device subscribes to the `monitor` topic,
about once per second, and stops cleanly with the app. Sustained heavy CPU load becomes a
`mac_heavy_load` Signal (Expression only, never speech).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from app.monitoring.sampler import Sampler
from app.signals import Importance, Signal

logger = logging.getLogger(__name__)

MONITOR_TOPIC = "monitor"
HEAVY_LOAD_KIND = "mac_heavy_load"
HEAVY_LOAD_PERCENT = 85.0
HEAVY_LOAD_SECONDS = 120.0
SMOOTHING_SAMPLES = 5
DEFAULT_INTERVAL_SECONDS = 1.0


class HeavyLoadDetector:
    """True once, when smoothed CPU has stayed above the threshold for the whole window.

    It re-arms only after the load drops to the threshold or below, so a Mac that stays busy
    produces one Signal, not one per window.
    """

    def __init__(
        self,
        threshold: float = HEAVY_LOAD_PERCENT,
        window: float = HEAVY_LOAD_SECONDS,
        smoothing: int = SMOOTHING_SAMPLES,
    ) -> None:
        self._threshold = threshold
        self._window = window
        self._smoothing = smoothing
        self.reset()

    def reset(self) -> None:
        self._recent: list[float] = []
        self._since: float | None = None
        self._fired = False

    def feed(self, now: float, cpu_percent: float) -> bool:
        self._recent.append(cpu_percent)
        del self._recent[: -self._smoothing]
        average = sum(self._recent) / len(self._recent)
        if average <= self._threshold:
            self._since = None
            self._fired = False
            return False
        if self._since is None:
            self._since = now
        if not self._fired and now - self._since >= self._window:
            self._fired = True
            return True
        return False


class Monitoring:
    def __init__(
        self,
        fastapi_app: FastAPI,
        sampler: Sampler | None = None,
        *,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._app = fastapi_app
        self._sampler = sampler
        self._interval = interval
        self._clock = clock or time.monotonic
        self.detector = HeavyLoadDetector()
        self._task: asyncio.Task[None] | None = None
        self._active = False
        self._skip_detector = False

    def subscribed(self) -> bool:
        hub = getattr(self._app.state, "device_hub", None)
        if hub is None:
            return False
        return any(MONITOR_TOPIC in (entry.get("topics") or ()) for entry in list(hub.entries))

    async def tick(self) -> dict[str, Any] | None:
        """Collect and publish once if someone is subscribed; return the sample or None."""
        if not self.subscribed():
            if self._active:
                self._active = False
                self.detector.reset()
                if self._sampler is not None:
                    self._sampler.reset()
            return None
        if self._sampler is None:
            self._sampler = Sampler()
        if not self._active:
            # First tick after a (re)subscribe: start the CPU counters and keep this reading
            # (taken over a very short window) out of the heavy-load detector.
            await asyncio.to_thread(self._sampler.prime)
            self._skip_detector = True
        self._active = True
        snapshot = await asyncio.to_thread(self._sampler.sample)
        await self._app.state.device_hub.publish(MONITOR_TOPIC, snapshot)
        if self._skip_detector:
            self._skip_detector = False
        elif self.detector.feed(self._clock(), snapshot["cpu"]["percent"]):
            await self._emit_heavy_load(snapshot["cpu"]["percent"])
        return snapshot

    async def _emit_heavy_load(self, percent: float) -> None:
        bus = getattr(self._app.state, "signals", None)
        if bus is None:
            return
        try:
            await bus.emit(
                Signal(
                    kind=HEAVY_LOAD_KIND,
                    source="monitor",
                    importance=Importance.NORMAL,
                    summary="The Mac has been under heavy load.",
                    data={"cpu_percent": round(percent, 1)},
                )
            )
        except Exception as exc:
            logger.warning("Heavy load signal was not emitted (%s).", type(exc).__name__)

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.warning("Monitor tick failed (%s).", type(exc).__name__)
            await asyncio.sleep(self._interval)


def register(fastapi_app: FastAPI, sampler: Sampler | None = None, **kwargs: Any) -> Monitoring:
    monitoring = Monitoring(fastapi_app, sampler, **kwargs)
    fastapi_app.state.monitoring = monitoring
    return monitoring
