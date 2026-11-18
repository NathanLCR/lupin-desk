"""Tests for the Kokoro engine and the LupinTTS wrapper. Kokoro is always mocked; nothing is downloaded."""

from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import wave
from pathlib import Path

import pytest

from app import speech
from app.kokoro_tts import KOKORO_SAMPLE_RATE, KokoroEngine, LupinTTS
from app.tts import ServerTTS


class _Chunk:
    """Mimics a Kokoro pipeline result with an `.audio` attribute."""

    def __init__(self, audio):
        self.audio = audio


class _FakeTensor:
    """Mimics a torch tensor: detach/cpu/numpy/tolist."""

    def __init__(self, values):
        self._values = list(values)

    def detach(self):
        return self

    def cpu(self):
        return self

    def numpy(self):
        return list(self._values)

    def tolist(self):
        return list(self._values)


class FakeKokoro:
    """Records factory and pipeline calls; yields object-style and tuple-style results."""

    def __init__(self, fail_with: Exception | None = None):
        self.fail_with = fail_with
        self.factory_calls: list[str] = []
        self.pipeline_calls: list[tuple[str, str | None, str]] = []

    def factory(self, lang_code: str):
        self.factory_calls.append(lang_code)
        if self.fail_with is not None:
            raise self.fail_with

        def pipeline(text, voice=None, **_kwargs):
            self.pipeline_calls.append((lang_code, voice, text))
            yield _Chunk([0.0, 0.5, -0.5])
            yield ("graphemes", "phonemes", [1.0, -1.0])
            yield _Chunk(_FakeTensor([0.25]))

        return pipeline


class FakeRunner:
    """Stands in for subprocess.run; `afconvert` writes its output file (argv[-1])."""

    def __init__(self):
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        Path(argv[-1]).write_bytes(b"m4a-bytes")
        return subprocess.CompletedProcess(argv, 0, "", "")


def _read_wav(data: bytes):
    with wave.open(io.BytesIO(data), "rb") as wav_file:
        return (
            wav_file.getnchannels(),
            wav_file.getframerate(),
            wav_file.getsampwidth(),
            wav_file.readframes(wav_file.getnframes()),
        )


def _say_fallback(calls: list | None = None) -> ServerTTS:
    def synth(text, voice, fmt):
        if calls is not None:
            calls.append((text, voice, fmt))
        return b"say-bytes"

    return ServerTTS(synth_fn=synth)


def test_wav_output_is_mono_24k_16bit():
    kokoro = FakeKokoro()
    engine = KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner(), language_getter=lambda: "en")

    data, mime = engine.synthesize("Hello there", None, "wav")

    assert mime == "audio/wav"
    channels, rate, width, frames = _read_wav(data)
    assert channels == 1
    assert rate == KOKORO_SAMPLE_RATE == 24000
    assert width == 2
    # 3 + 2 + 1 samples from the three chunks
    assert len(frames) == 6 * 2


def test_wav_clips_out_of_range_samples():
    kokoro = FakeKokoro()
    engine = KokoroEngine(pipeline_factory=lambda code: lambda text, voice=None: [_Chunk([2.0, -3.0])])
    data, _ = engine.synthesize("Clip me", None, "wav")
    _, _, _, frames = _read_wav(data)
    samples = [int.from_bytes(frames[i : i + 2], "little", signed=True) for i in range(0, len(frames), 2)]
    assert samples == [32767, -32767]


def test_m4a_goes_through_afconvert_argv_without_shell():
    kokoro = FakeKokoro()
    runner = FakeRunner()
    engine = KokoroEngine(pipeline_factory=kokoro.factory, runner=runner, language_getter=lambda: "en")

    data, mime = engine.synthesize("Hello", None, "m4a")

    assert mime == "audio/mp4"
    assert data == b"m4a-bytes"
    assert len(runner.calls) == 1
    argv, kwargs = runner.calls[0]
    assert argv[0] == "/usr/bin/afconvert"
    assert argv[1:5] == ["-f", "m4af", "-d", "aac"]
    assert argv[5].endswith(".wav") and argv[6].endswith(".m4a")
    assert isinstance(argv, list)
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 30


def test_afconvert_failure_raises_runtime_error():
    kokoro = FakeKokoro()

    def failing_runner(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 1, "", "boom")

    engine = KokoroEngine(pipeline_factory=kokoro.factory, runner=failing_runner, language_getter=lambda: "en")
    with pytest.raises(RuntimeError):
        engine.synthesize("Hello", None, "m4a")


def test_voice_selection_by_language_and_override():
    kokoro = FakeKokoro()
    lang = {"value": "pt-BR"}
    engine = KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner(), language_getter=lambda: lang["value"])

    engine.synthesize("Oi", None, "wav")
    assert kokoro.pipeline_calls[-1][:2] == ("p", "pf_dora")

    lang["value"] = "en"
    engine.synthesize("Hi", None, "wav")
    assert kokoro.pipeline_calls[-1][:2] == ("a", "af_heart")

    engine.synthesize("Hi", "Luciana", "wav")
    assert kokoro.pipeline_calls[-1][:2] == ("a", "af_heart")

    engine.synthesize("Hi", "bf_emma", "wav")
    assert kokoro.pipeline_calls[-1][:2] == ("a", "bf_emma")


def test_default_language_getter_uses_speech_module(monkeypatch):
    kokoro = FakeKokoro()
    monkeypatch.setattr(speech, "get_language", lambda: "en")
    engine = KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner())

    engine.synthesize("Hi", None, "wav")

    assert kokoro.pipeline_calls[-1][:2] == ("a", "af_heart")


def test_pipeline_is_cached_per_language():
    kokoro = FakeKokoro()
    lang = {"value": "pt-BR"}
    engine = KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner(), language_getter=lambda: lang["value"])

    engine.synthesize("Um", None, "wav")
    engine.synthesize("Dois", None, "wav")
    lang["value"] = "en"
    engine.synthesize("Three", None, "wav")
    engine.synthesize("Four", None, "wav")

    assert kokoro.factory_calls == ["p", "a"]


def test_empty_text_raises_value_error_and_does_not_fall_back():
    say_calls: list = []
    kokoro = FakeKokoro()
    lupin = LupinTTS(
        fallback=_say_fallback(say_calls),
        kokoro=KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner()),
    )

    with pytest.raises(ValueError):
        lupin.synthesize("   ", None, "m4a")
    with pytest.raises(ValueError):
        lupin.synthesize("Hello", None, "mp3")

    assert say_calls == []
    assert kokoro.factory_calls == []


def test_kokoro_failure_falls_back_to_say():
    say_calls: list = []
    kokoro = FakeKokoro(fail_with=RuntimeError("model exploded"))
    lupin = LupinTTS(fallback=_say_fallback(say_calls), kokoro=KokoroEngine(pipeline_factory=kokoro.factory))

    data, mime = lupin.synthesize("Oi, tudo bem?", "Luciana", "m4a")

    assert (data, mime) == (b"say-bytes", "audio/mp4")
    assert say_calls == [("Oi, tudo bem?", "Luciana", "m4a")]
    assert lupin.engine == "say"


def test_synthesis_error_falls_back_and_does_not_leak_text(caplog):
    say_calls: list = []

    def pipeline_that_raises(text, voice=None):
        raise ValueError("secret text should not be logged")

    engine = KokoroEngine(pipeline_factory=lambda code: pipeline_that_raises, runner=FakeRunner())
    lupin = LupinTTS(fallback=_say_fallback(say_calls), kokoro=engine)

    with caplog.at_level("WARNING"):
        data, _ = lupin.synthesize("my private words", None, "wav")

    assert data == b"say-bytes"
    assert "ValueError" in caplog.text
    assert "my private words" not in caplog.text
    assert "secret text" not in caplog.text


def test_factory_failure_marks_engine_broken_and_is_not_retried():
    say_calls: list = []
    kokoro = FakeKokoro(fail_with=ImportError("no kokoro"))
    engine = KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner(), language_getter=lambda: "pt-BR")
    lupin = LupinTTS(fallback=_say_fallback(say_calls), kokoro=engine)

    assert lupin.synthesize("Primeira", None, "wav")[0] == b"say-bytes"
    assert engine.usable() is False
    assert lupin.synthesize("Segunda", None, "wav")[0] == b"say-bytes"

    assert kokoro.factory_calls == ["p"]
    assert len(say_calls) == 2


def test_disabled_never_calls_kokoro():
    kokoro = FakeKokoro()
    lupin = LupinTTS(
        fallback=_say_fallback(),
        kokoro=KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner()),
        enabled=False,
    )

    assert lupin.synthesize("Oi", None, "m4a")[0] == b"say-bytes"
    assert lupin.is_available() is True
    assert lupin.engine == "say"
    assert kokoro.factory_calls == []


def test_is_available_true_when_only_fallback_available(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *args, **kwargs: None)
    lupin = LupinTTS(fallback=_say_fallback(), kokoro=KokoroEngine())
    assert lupin.is_available() is True
    assert lupin.engine == "say"


def test_is_installed_false_when_kokoro_absent(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *args, **kwargs: None)
    assert KokoroEngine().is_installed() is False
    assert KokoroEngine().usable() is False


def test_is_installed_true_with_injected_factory(monkeypatch):
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *args, **kwargs: None)
    assert KokoroEngine(pipeline_factory=FakeKokoro().factory).is_installed() is True


def test_is_installed_never_raises(monkeypatch):
    def boom(name, *args, **kwargs):
        raise ValueError("broken spec")

    monkeypatch.setattr(importlib.util, "find_spec", boom)
    assert KokoroEngine().is_installed() is False


def test_numpy_missing_uses_pure_python_path(monkeypatch):
    monkeypatch.setitem(sys.modules, "numpy", None)
    kokoro = FakeKokoro()
    engine = KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner(), language_getter=lambda: "en")

    data, _ = engine.synthesize("Hi", None, "wav")

    _, _, _, frames = _read_wav(data)
    samples = [int.from_bytes(frames[i : i + 2], "little", signed=True) for i in range(0, len(frames), 2)]
    assert samples == [0, 16384, -16384, 32767, -32767, 8192]


def test_no_audio_raises_runtime_error():
    engine = KokoroEngine(pipeline_factory=lambda code: lambda text, voice=None: [], runner=FakeRunner())
    with pytest.raises(RuntimeError):
        engine.synthesize("Silence", None, "wav")


async def test_async_path_uses_kokoro():
    kokoro = FakeKokoro()
    lupin = LupinTTS(
        fallback=_say_fallback(),
        kokoro=KokoroEngine(pipeline_factory=kokoro.factory, runner=FakeRunner(), language_getter=lambda: "en"),
    )

    data, mime = await lupin.synthesize_async("Async hello", None, "wav")

    assert mime == "audio/wav"
    assert _read_wav(data)[1] == KOKORO_SAMPLE_RATE
    assert lupin.engine == "kokoro"


async def test_async_path_falls_back_to_say():
    say_calls: list = []
    kokoro = FakeKokoro(fail_with=RuntimeError("nope"))
    lupin = LupinTTS(fallback=_say_fallback(say_calls), kokoro=KokoroEngine(pipeline_factory=kokoro.factory))

    data, mime = await lupin.synthesize_async("Olá", "Luciana", "m4a")

    assert (data, mime) == (b"say-bytes", "audio/mp4")
    assert say_calls and say_calls[0][0] == "Olá"


async def test_async_empty_text_raises_without_fallback():
    say_calls: list = []
    lupin = LupinTTS(fallback=_say_fallback(say_calls), kokoro=KokoroEngine(pipeline_factory=FakeKokoro().factory))
    with pytest.raises(ValueError):
        await lupin.synthesize_async("", None, "m4a")
    assert say_calls == []


def test_default_voice_and_list_voices_delegate_to_fallback():
    fallback = ServerTTS(default_voice="Luciana", synth_fn=lambda t, v, f: b"x")
    lupin = LupinTTS(fallback=fallback, kokoro=KokoroEngine(pipeline_factory=FakeKokoro().factory))
    assert lupin.default_voice == "Luciana"
    assert lupin.list_voices() == fallback.list_voices()

