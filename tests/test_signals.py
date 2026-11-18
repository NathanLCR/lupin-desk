"""Unit tests for the Brain-side Signals bus: publishing, Lupin's reactions, rate limits, consent."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app import speech, speech_en, speech_pt_br  # noqa: E402
from app.actions import ActionRegistry  # noqa: E402
from app.device_hub import DeviceHub  # noqa: E402
from app.devices import DeviceStore  # noqa: E402
from app.signals import (  # noqa: E402
    KIND_EXPRESSIONS,
    RATE_LIMIT_SECONDS,
    SIGNALS_TOPIC,
    Importance,
    Signal,
    SignalBus,
)


class FakeHub:
    """Records every publish; every topic counts as delivered once."""

    def __init__(self) -> None:
        self.published: list[tuple[str, Any]] = []

    async def publish(self, topic: str, payload: Any) -> int:
        self.published.append((topic, payload))
        return 1


class Recorder:
    """Speak and expression callbacks that record what Lupin did."""

    def __init__(self) -> None:
        self.spoken: list[str] = []
        self.expressions: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)

    async def set_expression(self, name: str) -> None:
        self.expressions.append(name)


class Clock:
    def __init__(self) -> None:
        self.now = [0.0]

    def __call__(self) -> float:
        return self.now[0]


def _bus(hub: Any = None, recorder: Recorder | None = None, clock: Clock | None = None) -> tuple[SignalBus, Recorder]:
    recorder = recorder or Recorder()
    bus = SignalBus(hub, speak=recorder.speak, set_expression=recorder.set_expression, clock=clock or Clock())
    return bus, recorder


def _build_failed(summary: str = "The build failed on main.") -> Signal:
    return Signal(kind="build_failed", source="build-watch", importance=Importance.IMPORTANT, summary=summary)


@pytest.fixture
def language():
    """Restore the Brain's spoken language after a test changes it."""
    previous = speech.get_language()
    yield
    speech.set_language(previous)


def test_source_signal_reaches_widget_topics_and_lupin_speaks() -> None:
    hub = FakeHub()
    bus, recorder = _bus(hub)

    result = asyncio.run(bus.emit(_build_failed()))

    assert [topic for topic, _ in hub.published] == [SIGNALS_TOPIC, "signal:build_failed"]
    assert hub.published[0][1]["kind"] == "build_failed"
    assert hub.published[0][1]["importance"] == "important"
    assert result.published == 2
    assert result.spoke is True
    assert result.reason == "spoken"
    assert result.expression == "sad"
    assert recorder.spoken == ["The build failed on main."]
    assert recorder.expressions == ["sad"]


def test_real_device_hub_delivers_signal_to_subscribed_widget(tmp_path: Path) -> None:
    hub = DeviceHub(DeviceStore(tmp_path / "devices.db"), ActionRegistry())
    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    async def setup() -> dict[str, Any]:
        body_info: dict[str, Any] = {}
        await hub.hello(body_info, {"body": "esp32"}, send)
        entry = body_info["entry"]
        await hub.handle_message(
            entry, {"type": "subscribe", "topics": [SIGNALS_TOPIC, "signal:build_failed"]}, send
        )
        return entry

    asyncio.run(setup())
    recorder = Recorder()
    bus = SignalBus(hub, speak=recorder.speak, set_expression=recorder.set_expression)

    result = asyncio.run(bus.emit(_build_failed()))

    topic_messages = [m for m in messages if m.get("type") == "topic"]
    assert [m["topic"] for m in topic_messages] == [SIGNALS_TOPIC, "signal:build_failed"]
    assert topic_messages[0]["data"]["summary"] == "The build failed on main."
    assert result.published == 2
    assert recorder.spoken == ["The build failed on main."]


def test_unimportant_signals_never_speak() -> None:
    hub = FakeHub()
    bus, recorder = _bus(hub)

    low = asyncio.run(bus.emit(Signal(kind="weather_update", source="x", importance=Importance.LOW, summary="Rain.")))
    important = asyncio.run(
        bus.emit(Signal(kind="cpu_hot", source="x", importance=Importance.IMPORTANT, summary="Hot CPU."))
    )
    normal = asyncio.run(bus.emit(Signal(kind="weather_update", source="x", summary="Sun.")))

    assert recorder.spoken == []
    assert low.spoke is False and important.spoke is False and normal.spoke is False
    assert important.reason == "silent"
    assert important.expression is None
    assert normal.reason == "expression_only"
    assert [topic for topic, _ in hub.published].count(SIGNALS_TOPIC) == 3


def test_during_focus_only_claude_code_speaks(language) -> None:
    speech.set_language("en")
    recorder = Recorder()
    bus, _ = _bus(FakeHub(), recorder)
    bus.focus_active = lambda: True

    for kind in ("build_failed", "timer_done", "meeting_soon"):
        result = asyncio.run(bus.emit(Signal(kind=kind, source="x", summary="Something.")))
        assert result.spoke is False
        assert result.reason == "focus"
        assert result.expression is None

    assert recorder.spoken == []
    assert recorder.expressions == []

    result = asyncio.run(bus.emit(Signal(kind="claude_code_needs_user", source="claude-code")))
    assert result.spoke is True
    assert recorder.spoken == ["Claude Code needs you."]
    assert recorder.expressions == [KIND_EXPRESSIONS["claude_code_needs_user"]]


def test_rate_limit_suppresses_repeat_speech_but_still_publishes() -> None:
    clock = Clock()
    hub = FakeHub()
    bus, recorder = _bus(hub, clock=clock)
    limit = RATE_LIMIT_SECONDS["claude_code_needs_user"]
    signal = Signal(kind="claude_code_needs_user", source="claude-code", summary="Question for you.")

    first = asyncio.run(bus.emit(signal))
    assert first.spoke is True

    clock.now[0] = 30.0
    second = asyncio.run(bus.emit(signal))
    assert second.spoke is False
    assert second.reason == "rate_limited"
    assert second.expression is None
    assert second.published == 2
    assert len(hub.published) == 4
    assert recorder.spoken == ["Question for you."]
    assert recorder.expressions == ["curious"]

    # A rate-limited signal does not reset the timer: 60s after the spoken one, it speaks again.
    clock.now[0] = limit - 1
    assert asyncio.run(bus.emit(signal)).reason == "rate_limited"
    clock.now[0] = limit
    third = asyncio.run(bus.emit(signal))
    assert third.spoke is True
    assert len(recorder.spoken) == 2


def test_rate_limits_are_independent_per_kind() -> None:
    clock = Clock()
    bus, recorder = _bus(FakeHub(), clock=clock)

    assert asyncio.run(bus.emit(_build_failed())).spoke is True
    clock.now[0] = 1.0
    assert asyncio.run(bus.emit(_build_failed())).reason == "rate_limited"

    timer = Signal(kind="timer_done", source="timer", summary="Tea is ready.")
    assert asyncio.run(bus.emit(timer)).spoke is True
    assert recorder.spoken == ["The build failed on main.", "Tea is ready."]


def test_spoken_text_falls_back_to_signal_lines_in_current_language(language) -> None:
    bus, recorder = _bus(FakeHub())

    speech.set_language("en")
    asyncio.run(bus.emit(Signal(kind="build_failed", source="ci", importance=Importance.IMPORTANT)))
    assert recorder.spoken[-1] == speech_en.SIGNAL_LINES["build_failed"] == "The build failed."

    clock = Clock()
    bus, recorder = _bus(FakeHub(), clock=clock)
    speech.set_language("pt-BR")
    asyncio.run(bus.emit(Signal(kind="timer_done", source="timer", summary="   ")))
    assert recorder.spoken == [speech_pt_br.SIGNAL_LINES["timer_done"]] == ["Seu timer acabou."]


def test_llm_view_hides_sensitive_contents_without_consent() -> None:
    consent: dict[str, bool] = {"calendar": False, "email": False}
    bus = SignalBus(consent=lambda: dict(consent))

    calendar = Signal(
        kind="meeting_soon", source="calendar", summary="Standup with Ana", data={"title": "Standup"}, data_class="calendar"
    )
    assert bus.llm_view(calendar) == {"kind": "meeting_soon", "source": "calendar", "importance": "normal"}

    consent["calendar"] = True
    shown = bus.llm_view(calendar)
    assert shown["summary"] == "Standup with Ana"
    assert shown["data"] == {"title": "Standup"}

    email = Signal(kind="mail_arrived", source="mail", summary="From Bo", data={"subject": "x"}, data_class="email")
    assert "summary" not in bus.llm_view(email)
    consent["email"] = True
    assert bus.llm_view(email)["summary"] == "From Bo"


def test_llm_view_never_shows_files_and_always_shows_plain_signals() -> None:
    bus = SignalBus(consent=lambda: {"calendar": True, "email": True, "files": True})
    files = Signal(kind="file_changed", source="files", summary="notes.md", data={"path": "x"}, data_class="files")
    assert bus.llm_view(files) == {"kind": "file_changed", "source": "files", "importance": "normal"}

    plain = Signal(kind="build_failed", source="ci", summary="Red", data={"log": "x"})
    assert bus.llm_view(plain) == plain.to_dict()


def test_llm_view_without_consent_callable_hides_sensitive_data() -> None:
    bus = SignalBus()
    email = Signal(kind="mail_arrived", source="mail", summary="From Bo", data_class="email")
    assert "summary" not in bus.llm_view(email)


def test_listener_hook_receives_signals_and_removal_works() -> None:
    bus, recorder = _bus(FakeHub())
    seen: list[Signal] = []
    remove = bus.add_listener(seen.append)

    asyncio.run(bus.emit(_build_failed()))
    assert [s.kind for s in seen] == ["build_failed"]

    remove()
    asyncio.run(bus.emit(_build_failed()))
    assert len(seen) == 1
    remove()  # removing twice is harmless


def test_raising_listener_does_not_block_speech_or_other_listeners() -> None:
    bus, recorder = _bus(FakeHub())
    seen: list[str] = []

    def broken(signal: Signal) -> None:
        raise RuntimeError("boom")

    async def healthy(signal: Signal) -> None:
        seen.append(signal.kind)

    bus.add_listener(broken)
    bus.add_listener(healthy)

    result = asyncio.run(bus.emit(_build_failed()))

    assert seen == ["build_failed"]
    assert result.spoke is True
    assert recorder.spoken == ["The build failed on main."]


def test_raising_speak_callback_does_not_make_emit_raise() -> None:
    async def broken_speak(text: str) -> None:
        raise RuntimeError("audio device gone")

    hub = FakeHub()
    bus = SignalBus(hub, speak=broken_speak)

    result = asyncio.run(bus.emit(_build_failed()))

    assert result.spoke is False
    assert result.reason == "speak_failed"
    assert result.published == 2


def test_sync_speak_and_expression_callbacks_are_supported() -> None:
    spoken: list[str] = []
    expressions: list[str] = []
    bus = SignalBus(None, speak=spoken.append, set_expression=expressions.append)

    result = asyncio.run(bus.emit(_build_failed()))

    assert result.published == 0
    assert spoken == ["The build failed on main."]
    assert expressions == ["sad"]


def test_emit_rejects_empty_kind_or_source() -> None:
    bus, _ = _bus(FakeHub())
    with pytest.raises(ValueError):
        asyncio.run(bus.emit(Signal(kind="", source="ci")))
    with pytest.raises(ValueError):
        asyncio.run(bus.emit(Signal(kind="build_failed", source="")))


def test_active_body_speaker_sends_notice_audio_and_expression() -> None:
    from app.signals import ActiveBodySpeaker

    sent: list[dict] = []

    async def send(payload: dict) -> None:
        sent.append(payload)

    class FakeTTS:
        def is_available(self) -> bool:
            return True

        async def synthesize_async(self, text: str, voice: str | None, output_format: str):
            return b"x" * 5, "audio/mp4"

    entry = {"send": send, "wants_audio": True, "body": "mac"}
    speaker = ActiveBodySpeaker(lambda: entry, FakeTTS(), lambda: "v", chunk_bytes=2)
    asyncio.run(speaker.speak("hi"))
    asyncio.run(speaker.set_expression("sad"))
    assert sent[0] == {"type": "notice", "kind": "signal", "text": "hi"}
    audio = [m for m in sent if m["type"] == "audio"]
    assert len(audio) == 3 and audio[-1]["last"] and not audio[0]["last"]
    assert sent[-1] == {"type": "emotion", "emotion": "sad"}

    sent.clear()
    entry["wants_audio"] = False
    asyncio.run(speaker.speak("hi"))
    assert [m["type"] for m in sent] == ["notice"]

    none_speaker = ActiveBodySpeaker(lambda: None)
    asyncio.run(none_speaker.speak("hi"))
    asyncio.run(none_speaker.set_expression("sad"))


def test_mac_controller_pomodoro_active_follows_start_and_stop() -> None:
    from app.mac_control import MacController

    mac = MacController(runner=lambda *a, **k: None)
    assert mac.pomodoro_active() is False
    mac.execute_mac_command("pomodoro_start")
    assert mac.pomodoro_active() is True
    mac.execute_mac_command("pomodoro_stop")
    assert mac.pomodoro_active() is False
