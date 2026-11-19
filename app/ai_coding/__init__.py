"""AI coding (P09): Claude Code and Codex sessions, quotas, GitHub and permission prompts.

`register(app, ...)` builds the service, the routes and the Panel actions. The service publishes a
snapshot on the `ai-coding` topic about every 5 seconds while a Panel is subscribed, and the
pending permission prompts on `ai-coding-prompts`. GitHub is polled every 5 minutes through the
`gh` login; a new failing CI run becomes one `build_failed` Signal.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.actions import CURRENT_CALLER
from app.ai_coding.github import GitHubWatcher, Runner
from app.ai_coding.hooks import HooksInstaller
from app.ai_coding.permissions import PROMPTS_TOPIC, PermissionBroker
from app.ai_coding.quotas import build_quotas
from app.ai_coding.routes import setup_routes
from app.ai_coding.sessions import SessionReader
from app.signals import Importance, Signal

logger = logging.getLogger(__name__)

AI_CODING_TOPIC = "ai-coding"
BUILD_FAILED_KIND = "build_failed"
DEFAULT_INTERVAL_SECONDS = 5.0
GITHUB_INTERVAL_SECONDS = 300.0


class AiCoding:
    def __init__(
        self,
        fastapi_app: FastAPI,
        reader: SessionReader,
        installer: HooksInstaller,
        github: GitHubWatcher,
        *,
        interval: float = DEFAULT_INTERVAL_SECONDS,
        github_interval: float = GITHUB_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._app = fastapi_app
        self.reader = reader
        self.installer = installer
        self.github = github
        self._interval = interval
        self._github_interval = github_interval
        self._clock = clock
        self._github_at: float | None = None
        self._task: asyncio.Task[None] | None = None
        self.broker = PermissionBroker(
            lambda: getattr(fastapi_app.state, "device_hub", None),
            lambda: getattr(fastapi_app.state, "signals", None),
        )

    def _subscribed(self, topic: str) -> bool:
        hub = getattr(self._app.state, "device_hub", None)
        return hub is not None and any(topic in (e.get("topics") or ()) for e in list(hub.entries))

    async def snapshot(self) -> dict[str, Any]:
        now = self._clock()
        sessions = await asyncio.to_thread(self.reader.read, now)
        return {
            "sessions": [s.to_public(now) for s in sessions],
            "quotas": build_quotas(sessions, now),
            "github": self.github.state,
        }

    async def poll_github(self, force: bool = False) -> None:
        now = self._clock()
        if not force and self._github_at is not None and now - self._github_at < self._github_interval:
            return
        self._github_at = now
        sessions = await asyncio.to_thread(self.reader.read, now)
        cwds = [s.cwd for s in sessions]
        failures = await asyncio.to_thread(self.github.poll, cwds, now)
        bus = getattr(self._app.state, "signals", None)
        for failure in failures:
            if bus is None:
                break
            try:
                await bus.emit(
                    Signal(
                        kind=BUILD_FAILED_KIND,
                        source="github",
                        importance=Importance.IMPORTANT,
                        data={"repo": failure["repo"], "workflow": failure["name"]},
                    )
                )
            except Exception as exc:
                logger.warning("CI failure signal was not emitted (%s).", type(exc).__name__)

    async def tick(self) -> None:
        watched = self._subscribed(AI_CODING_TOPIC)
        # First look as soon as a Panel shows the widgets; otherwise every GITHUB_INTERVAL_SECONDS.
        await self.poll_github(force=watched and self.github.state["available"] is None)
        hub = getattr(self._app.state, "device_hub", None)
        if hub is not None and watched:
            await hub.publish(AI_CODING_TOPIC, await self.snapshot())
        if self.broker.pending():
            await self.broker.publish()

    def start(self) -> None:
        if self._task is None or self._task.done():
            # No `gh` call at boot: the first background look is one interval from now.
            self._github_at = self._clock()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        await self.broker.stop()
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _run(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                logger.warning("AI coding tick failed (%s).", type(exc).__name__)
            await asyncio.sleep(self._interval)


def _setup_actions(actions: Any, service: AiCoding) -> None:
    async def answer(args: dict[str, Any]) -> dict[str, Any]:
        accepted = service.broker.answer(CURRENT_CALLER.get(), args.get("id"), args.get("decision"))
        if accepted:
            await service.broker.publish()
        return {"accepted": accepted}

    async def refresh(_args: dict[str, Any]) -> dict[str, Any]:
        await service.poll_github(force=True)
        hub = getattr(service._app.state, "device_hub", None)
        if hub is not None:
            await hub.publish(AI_CODING_TOPIC, await service.snapshot())
        return {"ok": True}

    actions.register("ai_coding_answer", answer, "Allow or deny a Claude Code permission prompt.")
    actions.register("ai_coding_refresh", refresh, "Refresh AI coding sessions and GitHub status.")


def register(
    fastapi_app: FastAPI,
    *,
    port: int = 8000,
    claude_root: Path | None = None,
    codex_root: Path | None = None,
    settings_path: Path | None = None,
    state_path: Path | None = None,
    gh_runner: Runner | None = None,
    **kwargs: Any,
) -> AiCoding:
    """Wire AI coding into the app. Every path is injectable; the defaults are the user's real ones."""
    home = Path.home()
    service = AiCoding(
        fastapi_app,
        SessionReader(
            claude_root if claude_root is not None else home / ".claude" / "projects",
            codex_root if codex_root is not None else home / ".codex" / "sessions",
        ),
        HooksInstaller(
            settings_path if settings_path is not None else home / ".claude" / "settings.json",
            state_path if state_path is not None else home / ".claude" / "desk-assistant-hooks-backup.json",
            port,
        ),
        GitHubWatcher(gh_runner),
        **kwargs,
    )
    setup_routes(fastapi_app, service)
    actions = getattr(fastapi_app.state, "actions", None)
    if actions is not None:
        _setup_actions(actions, service)
    fastapi_app.state.ai_coding = service
    return service


__all__ = ["AI_CODING_TOPIC", "PROMPTS_TOPIC", "AiCoding", "register"]
