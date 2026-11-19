"""HTTP routes and Panel actions for the image editor.

LAN-reachable on purpose (Panels upload from other devices, ADR 0002). Nothing here lets a client
choose a path: uploads get random names inside the store, results go to the pictures folder, and
downloads are looked up by the random result id.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from app.actions import ActionRegistry
from app.images.service import MAX_UPLOAD_BYTES, TOPIC, ImageError, ImageService

Publish = Callable[[str, dict[str, Any]], Awaitable[Any]] | None


def _http(exc: ImageError) -> HTTPException:
    return HTTPException(status_code=exc.status, detail=exc.code)


async def publish_state(
    service: ImageService, publish: Publish, result: dict[str, Any] | None = None
) -> None:
    """Tell the Panels what is pending (and the latest result, when there is one)."""
    if publish is None:
        return
    await publish(TOPIC, {"pending": service.last_pending(), "result": result})


def setup_routes(app: FastAPI, service: ImageService, publish: Publish) -> None:
    @app.post("/api/images")
    async def upload_image(request: Request) -> dict[str, Any]:
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="too_large")
        try:
            info = await service.ingest(request.stream())
        except ImageError as exc:
            raise _http(exc) from exc
        await publish_state(service, publish)
        return info

    @app.get("/api/images/last")
    def last_image() -> dict[str, Any]:
        service.warm_up()  # a Panel opened the editor: compile the helper off the upload path
        return {"pending": service.last_pending()}

    @app.get("/api/images/{image_id}/preview")
    async def preview_image(image_id: str) -> FileResponse:
        found = await service.preview(image_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown_image")
        path, media_type = found
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})

    @app.post("/api/images/{image_id}/edit")
    async def edit_image(image_id: str, request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="bad_request") from exc
        ops = body.get("ops") if isinstance(body, dict) else None
        try:
            result = await service.edit(image_id, ops)
        except ImageError as exc:
            raise _http(exc) from exc
        await publish_state(service, publish, result)
        return result

    @app.delete("/api/images/{image_id}")
    async def discard_image(image_id: str) -> dict[str, bool]:
        if not service.discard(image_id):
            raise HTTPException(status_code=404, detail="unknown_image")
        await publish_state(service, publish)
        return {"ok": True}

    @app.get("/api/images/results/{result_id}")
    def download_result(result_id: str) -> FileResponse:
        found = service.result_file(result_id)
        if found is None:
            raise HTTPException(status_code=404, detail="unknown_result")
        path, name, media_type = found
        return FileResponse(path, media_type=media_type, filename=name)


def setup_actions(actions: ActionRegistry, service: ImageService, publish: Publish) -> None:
    """Panel actions: `image.edit {id?, ops}` and `image.discard {id}`."""

    async def image_edit(args: dict[str, Any]) -> dict[str, Any]:
        image_id = args.get("id")
        if image_id is not None and not isinstance(image_id, str):
            raise ValueError("id must be a string")
        try:
            result = await service.edit(image_id, args.get("ops"))
        except ImageError as exc:
            raise ValueError(exc.code) from exc
        await publish_state(service, publish, result)
        return result

    async def image_discard(args: dict[str, Any]) -> dict[str, Any]:
        image_id = args.get("id")
        if not isinstance(image_id, str) or not service.discard(image_id):
            raise ValueError("unknown image id")
        await publish_state(service, publish)
        return {"id": image_id, "discarded": True}

    actions.register("image.edit", image_edit, "Edit the uploaded image (crop, resize, compress, ...)")
    actions.register("image.discard", image_discard, "Delete an uploaded image without editing it")
