"""Tests for app/dictation.py: start/stop/cancel flow, paste results and error paths."""

from __future__ import annotations

import base64
from typing import Any

import pytest

from app.dictation import MAX_AUDIO_BYTES, DICTATION_TYPES, handle_dictation


class FakeSTT:
    def __init__(self, result: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self.result = result if result is not None else {"text": "hello world", "engine": "fake"}
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    async def transcribe_bytes(self, audio_bytes: bytes, mime_type: str, language: str) -> dict[str, Any]:
        self.calls.append({"audio_bytes": audio_bytes, "mime_type": mime_type, "language": language})
        if self.exc is not None:
            raise self.exc
        return self.result


class FakeMac:
    def __init__(self, result: dict[str, Any] | None = None, exc: Exception | None = None) -> None:
        self.result = result if result is not None else {"ok": True, "chars": 5}
        self.exc = exc
        self.pasted: list[str] = []

    def paste_text(self, text: str) -> dict[str, Any]:
        self.pasted.append(text)
        if self.exc is not None:
            raise self.exc
        return self.result


class Collector:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, payload: dict[str, Any]) -> None:
        self.messages.append(payload)


def _b64(raw: bytes = b"fake-audio") -> str:
    return base64.b64encode(raw).decode("ascii")


def _rules(text: str, language: str = "pt") -> str:
    return f"[{language}]{text.upper()}"


async def _run_stop(data: dict[str, Any], stt: FakeSTT, mac: FakeMac, language: str = "pt") -> list[dict[str, Any]]:
    send = Collector()
    await handle_dictation(
        "dictation_stop",
        data,
        stt=stt,
        mac=mac,
        send=send,
        language=language,
        rules=_rules,
    )
    return send.messages


def test_dictation_types_and_limit() -> None:
    assert DICTATION_TYPES == frozenset({"dictation_start", "dictation_stop", "dictation_cancel"})
    assert MAX_AUDIO_BYTES == 25 * 1024 * 1024


async def test_start_sends_listening_status_then_state() -> None:
    send = Collector()
    await handle_dictation(
        "dictation_start",
        {},
        stt=FakeSTT(),
        mac=FakeMac(),
        send=send,
        language="pt",
        rules=_rules,
    )
    assert send.messages == [
        {"type": "dictation", "status": "listening"},
        {"type": "state", "state": "listening"},
    ]


async def test_cancel_sends_idle_state_only() -> None:
    send = Collector()
    stt = FakeSTT()
    mac = FakeMac()
    await handle_dictation(
        "dictation_cancel",
        {},
        stt=stt,
        mac=mac,
        send=send,
        language="pt",
        rules=_rules,
    )
    assert send.messages == [{"type": "state", "state": "idle"}]
    assert stt.calls == []
    assert mac.pasted == []


async def test_unknown_type_is_ignored() -> None:
    send = Collector()
    await handle_dictation("chat", {}, stt=FakeSTT(), mac=FakeMac(), send=send, language="pt", rules=_rules)
    assert send.messages == []


async def test_stop_success_applies_rules_pastes_and_ends_idle() -> None:
    stt = FakeSTT({"text": "  ola mundo  ", "engine": "fake"})
    mac = FakeMac({"ok": True, "chars": 9})

    messages = await _run_stop({"data": _b64(), "language": "en"}, stt, mac, language="pt")

    assert stt.calls == [{"audio_bytes": b"fake-audio", "mime_type": "audio/webm", "language": "en"}]
    assert mac.pasted == ["[en]OLA MUNDO"]
    assert messages == [
        {"type": "state", "state": "thinking"},
        {
            "type": "dictation",
            "status": "done",
            "text": "[en]OLA MUNDO",
            "inserted": True,
            "needs_accessibility": False,
            "error": None,
        },
        {"type": "emotion", "emotion": "happy"},
        {"type": "state", "state": "idle"},
    ]


async def test_stop_uses_data_url_prefix_and_explicit_mime_and_default_language() -> None:
    stt = FakeSTT()
    mac = FakeMac()
    data = {"data": "data:audio/ogg;base64," + _b64(b"xyz"), "mime_type": "audio/ogg"}

    await _run_stop(data, stt, mac, language="pt")

    assert stt.calls[0]["audio_bytes"] == b"xyz"
    assert stt.calls[0]["mime_type"] == "audio/ogg"
    assert stt.calls[0]["language"] == "pt"


async def test_stop_empty_transcript_reports_empty_and_does_not_paste() -> None:
    stt = FakeSTT({"text": "   ", "engine": "fake"})
    mac = FakeMac()

    messages = await _run_stop({"data": _b64()}, stt, mac)

    assert mac.pasted == []
    assert messages == [
        {"type": "state", "state": "thinking"},
        {"type": "dictation", "status": "empty"},
        {"type": "state", "state": "idle"},
    ]


async def test_stop_stt_error_without_text_reports_error_message() -> None:
    stt = FakeSTT({"text": "", "engine": "fake", "error": "model not loaded"})
    mac = FakeMac()

    messages = await _run_stop({"data": _b64()}, stt, mac)

    assert mac.pasted == []
    assert messages == [
        {"type": "state", "state": "thinking"},
        {"type": "dictation", "status": "error", "error": "model not loaded"},
        {"type": "state", "state": "idle"},
    ]


async def test_stop_stt_empty_result_without_error_is_empty() -> None:
    stt = FakeSTT({"text": "", "engine": "fake", "error": None})
    messages = await _run_stop({"data": _b64()}, stt, FakeMac())
    assert messages[1] == {"type": "dictation", "status": "empty"}


async def test_stop_stt_exception_reports_generic_error() -> None:
    stt = FakeSTT(exc=RuntimeError("secret transcript fragment"))
    mac = FakeMac()

    messages = await _run_stop({"data": _b64()}, stt, mac)

    assert mac.pasted == []
    assert messages == [
        {"type": "state", "state": "thinking"},
        {"type": "dictation", "status": "error", "error": "Could not transcribe the audio."},
        {"type": "state", "state": "idle"},
    ]
    assert "secret" not in str(messages)


@pytest.mark.parametrize(
    "payload",
    [
        {"data": "!!!not base64!!!"},
        {"data": ""},
        {"data": "   "},
        {"data": "data:audio/webm;base64,"},
        {},
    ],
)
async def test_stop_invalid_or_empty_audio_is_rejected(payload: dict[str, Any]) -> None:
    stt = FakeSTT()
    mac = FakeMac()

    messages = await _run_stop(payload, stt, mac)

    assert stt.calls == []
    assert mac.pasted == []
    assert messages == [
        {"type": "dictation", "status": "error", "error": "Invalid audio."},
        {"type": "state", "state": "idle"},
    ]


async def test_stop_oversize_audio_is_rejected_before_transcription() -> None:
    stt = FakeSTT()
    mac = FakeMac()
    oversize = base64.b64encode(b"\x00" * (MAX_AUDIO_BYTES + 1)).decode("ascii")

    messages = await _run_stop({"data": oversize}, stt, mac)

    assert stt.calls == []
    assert mac.pasted == []
    assert messages == [
        {"type": "dictation", "status": "error", "error": "Invalid audio."},
        {"type": "state", "state": "idle"},
    ]


async def test_stop_paste_failure_reports_needs_accessibility() -> None:
    stt = FakeSTT({"text": "oi", "engine": "fake"})
    mac = FakeMac({"ok": False, "needs_accessibility": True, "error": "Accessibility permission missing"})

    messages = await _run_stop({"data": _b64()}, stt, mac)

    assert mac.pasted == ["[pt]OI"]
    assert messages == [
        {"type": "state", "state": "thinking"},
        {
            "type": "dictation",
            "status": "done",
            "text": "[pt]OI",
            "inserted": False,
            "needs_accessibility": True,
            "error": "Accessibility permission missing",
        },
        {"type": "state", "state": "idle"},
    ]


async def test_stop_paste_failure_without_accessibility_has_no_happy_emotion() -> None:
    stt = FakeSTT({"text": "oi", "engine": "fake"})
    mac = FakeMac({"ok": False, "needs_accessibility": False, "error": "no focused field"})

    messages = await _run_stop({"data": _b64()}, stt, mac)

    done = messages[1]
    assert done["inserted"] is False
    assert done["needs_accessibility"] is False
    assert done["error"] == "no focused field"
    assert not any(m.get("type") == "emotion" for m in messages)
    assert messages[-1] == {"type": "state", "state": "idle"}


async def test_paste_exception_reports_generic_error_and_ends_idle() -> None:
    stt = FakeSTT({"text": "oi", "engine": "fake"})
    mac = FakeMac(exc=OSError("osascript crashed"))

    messages = await _run_stop({"data": _b64()}, stt, mac)

    assert messages[-2] == {"type": "dictation", "status": "error", "error": "Dictation failed."}
    assert messages[-1] == {"type": "state", "state": "idle"}


async def test_rules_exception_reports_generic_error() -> None:
    def broken_rules(text: str, language: str) -> str:
        raise ValueError("bad rule")

    send = Collector()
    mac = FakeMac()
    await handle_dictation(
        "dictation_stop",
        {"data": _b64()},
        stt=FakeSTT(),
        mac=mac,
        send=send,
        language="pt",
        rules=broken_rules,
    )

    assert mac.pasted == []
    assert send.messages[-2] == {"type": "dictation", "status": "error", "error": "Dictation failed."}
    assert send.messages[-1] == {"type": "state", "state": "idle"}


async def test_default_rules_are_used_when_not_injected() -> None:
    """Smoke check: the default rules from app.dictation_rules run end to end."""
    send = Collector()
    mac = FakeMac()
    await handle_dictation(
        "dictation_stop",
        {"data": _b64()},
        stt=FakeSTT({"text": "teste simples", "engine": "fake"}),
        mac=mac,
        send=send,
        language="pt",
    )
    assert len(mac.pasted) == 1
    assert mac.pasted[0].strip()
    assert send.messages[-1] == {"type": "state", "state": "idle"}
