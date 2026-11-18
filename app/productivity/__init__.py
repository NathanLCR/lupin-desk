"""Tasks, notes and habits stored in the Brain's sqlite."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI

from app.productivity.routes import setup_actions, setup_routes
from app.productivity.scheduler import DEFAULT_INTERVAL_SECONDS, HabitScheduler
from app.productivity.store import ProductivityStore
from app.productivity.voice import VoiceActions


class Productivity:
    """Holds the store, the voice actions and the habit reminder scheduler."""

    def __init__(
        self,
        store: ProductivityStore,
        voice: VoiceActions,
        scheduler: HabitScheduler,
    ) -> None:
        self.store = store
        self.voice = voice
        self.scheduler = scheduler

    async def handle_voice(self, kind: str, target: str) -> dict[str, Any]:
        return await self.voice.handle(kind, target)

    def start(self) -> None:
        self.scheduler.start()

    async def stop(self) -> None:
        await self.scheduler.stop()
        self.store.close()


def register(
    fastapi_app: FastAPI,
    db_path: Path | str,
    *,
    clock: Callable[[], datetime] | None = None,
    interval: float = DEFAULT_INTERVAL_SECONDS,
) -> Productivity:
    """Wire the productivity store, routes, voice actions and scheduler into the app.

    Publishing and the Signals bus are looked up on each call, so the device hub and the
    signals may be set on app.state before or after this runs.
    """
    now = clock or datetime.now
    store = ProductivityStore(db_path, clock=now)

    async def publish(topic: str, payload: dict[str, Any]) -> None:
        hub = getattr(fastapi_app.state, "device_hub", None)
        if hub is None:
            return
        await hub.publish(topic, payload)

    voice = VoiceActions(store, publish)
    scheduler = HabitScheduler(
        store,
        lambda: getattr(fastapi_app.state, "signals", None),
        clock=now,
        interval=interval,
    )
    setup_routes(fastapi_app, store, publish)

    actions = getattr(fastapi_app.state, "actions", None)
    if actions is not None:
        setup_actions(actions, store, publish)

    productivity = Productivity(store, voice, scheduler)
    fastapi_app.state.productivity = productivity
    return productivity
