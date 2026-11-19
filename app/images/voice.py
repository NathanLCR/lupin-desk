"""Voice and LLM actions for the image editor: `[action:image:<verb>[:<arg>]]` tags.

They work on the most recent upload. Speech comes from the speech tables at call time.
Verbs: remove_background, resize:<pixels>, compress[:<quality>], convert:<format>.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app import speech
from app.images.service import ImageError, ImageService

logger = logging.getLogger(__name__)

DEFAULT_QUALITY = 70


def _op_for(verb: str, arg: str) -> dict[str, Any] | None:
    if verb in ("remove_background", "removebg", "cutout"):
        return {"op": "remove_background"}
    if verb == "resize":
        if not arg.isdigit():
            return None
        return {"op": "resize", "width": int(arg), "height": int(arg)}
    if verb == "compress":
        if arg and not arg.isdigit():
            return None
        return {"op": "compress", "quality": int(arg) if arg else DEFAULT_QUALITY}
    if verb == "convert":
        return {"op": "convert", "format": arg.lower().lstrip(".")} if arg else None
    return None


class VoiceActions:
    def __init__(
        self,
        service: ImageService,
        publish_result: Callable[[dict[str, Any]], Awaitable[Any]] | None = None,
    ) -> None:
        self._service = service
        self._publish_result = publish_result

    async def handle(self, kind: str, target: str) -> dict[str, Any]:
        verb, _, arg = str(target or "").partition(":")
        verb, arg = verb.strip().lower(), arg.strip()
        op = _op_for(verb, arg)
        if op is None:
            return self._reply(False, speech.image_failed(), verb)
        if self._service.last_pending() is None:
            return self._reply(False, speech.image_none(), verb)
        try:
            result = await self._service.edit(None, [op])
        except ImageError as exc:
            if exc.code == "unavailable":
                return self._reply(False, speech.image_unavailable(), verb)
            if exc.code == "no_subject":
                return self._reply(False, speech.image_no_subject(), verb)
            if exc.code == "unknown_image":
                return self._reply(False, speech.image_none(), verb)
            return self._reply(False, speech.image_failed(), verb)
        except Exception as exc:
            logger.warning("Voice image action failed (%s).", type(exc).__name__)
            return self._reply(False, speech.image_failed(), verb)
        if self._publish_result is not None:
            await self._publish_result(result)
        return self._reply(True, speech.image_done(result["name"]), verb)

    @staticmethod
    def _reply(ok: bool, spoken: str, verb: str) -> dict[str, Any]:
        return {"ok": ok, "spoken": spoken, "kind": "image", "verb": verb}
