"""Dictation: turn recorded speech into text and type it into the focused Mac app.

The WebSocket message types handled here are plain strings for now
(`dictation_start`, `dictation_stop`, `dictation_cancel`). They may move to
action IDs later; callers should route through `DICTATION_TYPES` so that
change stays in one place.

Audio and transcripts are never logged. Only exception type names and
lengths reach the log.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.dictation_rules import apply_dictation_rules

logger = logging.getLogger(__name__)

DICTATION_TYPES = frozenset({"dictation_start", "dictation_stop", "dictation_cancel"})
MAX_AUDIO_BYTES = 25 * 1024 * 1024

_DEFAULT_MIME_TYPE = "audio/webm"
_INVALID_AUDIO_MESSAGE = "Invalid audio."
_TRANSCRIBE_FAILED_MESSAGE = "Could not transcribe the audio."
_DICTATION_FAILED_MESSAGE = "Dictation failed."

SendFn = Callable[[dict[str, Any]], Awaitable[None]]


class _InvalidAudioError(ValueError):
    """Raised when the audio payload is missing, malformed or too large."""


def _decode_audio(raw_data: Any) -> bytes:
    """Decode base64 audio (optionally with a data: URL prefix) into bytes."""
    cleaned = str(raw_data or "").strip()
    if cleaned.startswith("data:") and "," in cleaned:
        cleaned = cleaned.split(",", 1)[1].strip()
    if not cleaned:
        raise _InvalidAudioError("empty audio")
    # Reject oversize payloads before decoding them into memory.
    if len(cleaned) > (MAX_AUDIO_BYTES * 4) // 3 + 4:
        raise _InvalidAudioError("audio too large")
    try:
        audio_bytes = base64.b64decode(cleaned, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _InvalidAudioError("invalid base64") from exc
    if not audio_bytes:
        raise _InvalidAudioError("empty audio")
    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise _InvalidAudioError("audio too large")
    return audio_bytes


async def _handle_stop(
    data: dict[str, Any],
    *,
    stt: Any,
    mac: Any,
    send: SendFn,
    language: str,
    rules: Callable[[str, str], str],
) -> None:
    try:
        audio_bytes = _decode_audio(data.get("data"))
    except _InvalidAudioError as exc:
        logger.info("Dictation audio rejected (%s)", type(exc).__name__)
        await send({"type": "dictation", "status": "error", "error": _INVALID_AUDIO_MESSAGE})
        await send({"type": "state", "state": "idle"})
        return

    mime_type = str(data.get("mime_type") or _DEFAULT_MIME_TYPE)
    lang = str(data.get("language") or language or "pt")

    await send({"type": "state", "state": "thinking"})

    try:
        stt_res = await stt.transcribe_bytes(
            audio_bytes=audio_bytes,
            mime_type=mime_type,
            language=lang,
        )
    except Exception as exc:
        logger.error("Dictation transcription failed (%s)", type(exc).__name__)
        await send({"type": "dictation", "status": "error", "error": _TRANSCRIBE_FAILED_MESSAGE})
        await send({"type": "state", "state": "idle"})
        return

    result = stt_res if isinstance(stt_res, dict) else {}
    raw_text = str(result.get("text") or "").strip()
    if not raw_text and result.get("error"):
        err_msg = str(result.get("error")) or _TRANSCRIBE_FAILED_MESSAGE
        await send({"type": "dictation", "status": "error", "error": err_msg})
        await send({"type": "state", "state": "idle"})
        return

    text = rules(raw_text, lang).strip() if raw_text else ""
    if not text:
        await send({"type": "dictation", "status": "empty"})
        await send({"type": "state", "state": "idle"})
        return

    res = await asyncio.to_thread(mac.paste_text, text)
    res = res if isinstance(res, dict) else {}
    inserted = bool(res.get("ok"))

    await send(
        {
            "type": "dictation",
            "status": "done",
            "text": text,
            "inserted": inserted,
            "needs_accessibility": bool(res.get("needs_accessibility")),
            "error": res.get("error"),
        }
    )
    if inserted:
        await send({"type": "emotion", "emotion": "happy"})
    await send({"type": "state", "state": "idle"})


async def handle_dictation(
    msg_type: str,
    data: dict[str, Any],
    *,
    stt: Any,
    mac: Any,
    send: SendFn,
    language: str,
    rules: Callable[[str, str], str] = apply_dictation_rules,
) -> None:
    """Handle one dictation WebSocket message.

    `msg_type` must be one of `DICTATION_TYPES`; other values are ignored.
    `data` is the parsed WebSocket message. `stt` must provide an async
    `transcribe_bytes(audio_bytes=, mime_type=, language=)`, `mac` a
    `paste_text(text) -> dict` method, and `send` an async callable taking a dict.
    """
    if msg_type not in DICTATION_TYPES:
        return

    try:
        if msg_type == "dictation_start":
            await send({"type": "dictation", "status": "listening"})
            await send({"type": "state", "state": "listening"})
        elif msg_type == "dictation_cancel":
            await send({"type": "state", "state": "idle"})
        else:
            await _handle_stop(
                data,
                stt=stt,
                mac=mac,
                send=send,
                language=language,
                rules=rules,
            )
    except Exception as exc:
        logger.error("Dictation handling failed (%s)", type(exc).__name__)
        try:
            await send({"type": "dictation", "status": "error", "error": _DICTATION_FAILED_MESSAGE})
            await send({"type": "state", "state": "idle"})
        except Exception as send_exc:
            logger.error("Could not report dictation failure (%s)", type(send_exc).__name__)
