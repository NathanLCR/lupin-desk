"""Image editor: Panels upload a photo, Lupin edits it locally (sips, macOS Vision)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI

from app.images.routes import publish_state, setup_actions, setup_routes
from app.images.service import ImageService
from app.images.tools import ImageTools
from app.images.voice import VoiceActions

DEFAULT_CACHE_DIR = Path.home() / "Library" / "Caches" / "Lupin" / "images"


class Images:
    """Holds the service and the voice actions (`app.state.images`)."""

    def __init__(self, service: ImageService, voice: VoiceActions) -> None:
        self.service = service
        self.voice = voice

    async def handle_voice(self, kind: str, target: str) -> dict[str, Any]:
        return await self.voice.handle(kind, target)


def register(
    fastapi_app: FastAPI,
    *,
    store_dir: Path | None = None,
    pictures_dir: Path | None = None,
    cache_dir: Path | None = None,
    tools: ImageTools | None = None,
    clock: Callable[[], datetime] = datetime.now,
) -> Images:
    """Wire the image routes, Panel actions and voice actions into the app.

    Every directory is injectable; tests pass `tmp_path`. The device hub is looked up per call.
    """
    resolved_tools = tools or ImageTools(cache_dir or DEFAULT_CACHE_DIR)
    service = ImageService(
        resolved_tools, store_dir=store_dir, pictures_dir=pictures_dir, clock=clock
    )

    async def publish(topic: str, payload: dict[str, Any]) -> None:
        hub = getattr(fastapi_app.state, "device_hub", None)
        if hub is not None:
            await hub.publish(topic, payload)

    async def publish_result(result: dict[str, Any]) -> None:
        await publish_state(service, publish, result)

    setup_routes(fastapi_app, service, publish)
    actions = getattr(fastapi_app.state, "actions", None)
    if actions is not None:
        setup_actions(actions, service, publish)

    images = Images(service, VoiceActions(service, publish_result))
    fastapi_app.state.images = images
    return images
