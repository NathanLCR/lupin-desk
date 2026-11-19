"""Control Deck and Automation (P10): system audio, macros, webhooks and rules.

`register(app, db_path, require_mac_client)` sets `app.state.control`. The Brain calls
`control.start()` / `await control.stop()` from its lifespan (starts the "app in front" poll and
subscribes the rules to the Signals bus).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.control.engine import MacroRunner, RulesEngine
from app.control.routes import setup_actions, setup_routes
from app.control.store import ControlStore
from app.control.system import SystemControl

logger = logging.getLogger(__name__)


class ControlDeck:
    def __init__(self, app: FastAPI, store: ControlStore, rules: RulesEngine, runner: MacroRunner) -> None:
        self._app = app
        self.store = store
        self.rules = rules
        self.runner = runner
        self._unsubscribe: Callable[[], None] | None = None

    def start(self) -> None:
        bus = getattr(self._app.state, "signals", None)
        if bus is not None and self._unsubscribe is None:
            self._unsubscribe = bus.add_listener(self.rules.on_signal)
        self.rules.start()

    async def stop(self) -> None:
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        await self.rules.stop()
        self.store.close()


def register(
    fastapi_app: FastAPI,
    db_path: Path | str,
    require_mac_client: Callable[..., Any],
    *,
    mac: Any = None,
    poll_seconds: float | None = None,
) -> ControlDeck:
    """Wire the store, actions, routes and rules engine. ``mac`` defaults to ``app.state.mac``."""
    mac = mac if mac is not None else getattr(fastapi_app.state, "mac", None)
    store = ControlStore(db_path)
    system = SystemControl(mac)

    async def publish(topic: str, payload: dict[str, Any]) -> None:
        hub = getattr(fastapi_app.state, "device_hub", None)
        if hub is not None:
            await hub.publish(topic, payload)

    def signals() -> Any:
        return getattr(fastapi_app.state, "signals", None)

    runner = MacroRunner(store, getattr(fastapi_app.state, "actions", None))
    kwargs: dict[str, Any] = {} if poll_seconds is None else {"poll_seconds": poll_seconds}
    rules = RulesEngine(store, publish, getattr(mac, "front_app", None), **kwargs)

    actions = getattr(fastapi_app.state, "actions", None)
    if actions is not None:
        setup_actions(
            actions, system, runner,
            shortcuts=getattr(fastapi_app.state, "shortcuts", None), mac=mac,
        )
    setup_routes(fastapi_app, store, system, require_mac_client, publish, signals)

    deck = ControlDeck(fastapi_app, store, rules, runner)
    fastapi_app.state.control = deck
    return deck
