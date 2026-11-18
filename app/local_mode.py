"""Local-mode helpers: a notice for when the local model is slow to answer."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class SlowModelNotice:
    """Fires `on_slow` once if `stop()` isn't called within `delay_s` seconds."""

    def __init__(self, delay_s: float, on_slow: Callable[[], Awaitable[None]] | None) -> None:
        self._delay_s = delay_s
        self._on_slow = on_slow
        self._task: asyncio.Task[None] | None = None
        self._fired = False

    def start(self) -> None:
        """Start the timer. Must be called inside a running event loop; idempotent."""
        if self._task is not None or self._fired:
            return
        if self._delay_s <= 0 or self._on_slow is None:
            return
        self._task = asyncio.get_running_loop().create_task(self._run())

    def stop(self) -> None:
        """Cancel the pending notice. Safe to call many times, before start, or after firing."""
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()

    @property
    def fired(self) -> bool:
        return self._fired

    async def _run(self) -> None:
        try:
            await asyncio.sleep(self._delay_s)
        except asyncio.CancelledError:
            return
        if self._on_slow is None:
            return
        self._fired = True
        try:
            await self._on_slow()
        except Exception as exc:  # noqa: BLE001 - the notice must never break the turn
            logger.warning("slow-model notice failed (%s)", type(exc).__name__)
