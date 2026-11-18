"""Lupin's voice: Kokoro (local neural TTS) with macOS `say` (`ServerTTS`) as the fallback.

Kokoro is an optional dependency (the `tts` extra in pyproject.toml). It is never imported at module
top level: `KokoroEngine` imports it lazily when the first pipeline is built. If it is missing, fails to
load, or fails to synthesize, `LupinTTS` falls back to `ServerTTS` so Lupin can always speak on macOS.
"""

from __future__ import annotations

import asyncio
import importlib.util
import io
import logging
import re
import struct
import subprocess
import tempfile
import threading
import wave
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from app import speech
from app.tts import _FORMAT_MIME_MAP, ServerTTS

logger = logging.getLogger(__name__)

KOKORO_SAMPLE_RATE = 24000
_AFCONVERT_BIN = "/usr/bin/afconvert"

_VOICES = {"pt-BR": "pf_dora", "en": "af_heart"}
_LANG_CODES = {"pt-BR": "p", "en": "a"}
_KOKORO_VOICE_RE = re.compile(r"^[a-z]{2}_[a-z]+$")


def _validate_request(text: str, output_format: str) -> tuple[str, str]:
    """Return the cleaned text and normalized format, or raise ValueError."""
    cleaned = " ".join((text or "").split())
    if not cleaned:
        raise ValueError("Text cannot be empty for speech synthesis.")
    fmt = (output_format or "m4a").strip().lower()
    if fmt not in _FORMAT_MIME_MAP:
        raise ValueError(f"Unsupported audio format: {fmt}. Use 'm4a' or 'wav'.")
    return cleaned, fmt


def _default_pipeline_factory(lang_code: str) -> Callable[..., Iterable[Any]]:
    from kokoro import KPipeline  # lazy: the package is optional

    return KPipeline(lang_code=lang_code)


def _audio_of(item: Any) -> Any:
    """Extract the audio from a pipeline result: an object with `.audio` or a (graphemes, phonemes, audio) tuple."""
    if hasattr(item, "audio"):
        return item.audio
    if isinstance(item, tuple) and len(item) == 3:
        return item[2]
    raise RuntimeError("Unexpected Kokoro pipeline output.")


def _to_pcm16(chunks: list[Any]) -> bytes:
    """Concatenate float audio chunks in [-1, 1] into little-endian 16-bit mono PCM."""
    try:
        import numpy as np
    except ImportError:
        np = None

    if np is not None:
        arrays = []
        for chunk in chunks:
            if hasattr(chunk, "detach"):
                chunk = chunk.detach().cpu().numpy()
            arrays.append(np.asarray(chunk, dtype=np.float32).reshape(-1))
        audio = np.concatenate(arrays) if arrays else np.zeros(0, dtype=np.float32)
        clipped = np.clip(audio, -1.0, 1.0)
        return np.round(clipped * 32767.0).astype("<i2").tobytes()

    # Pure-Python path, used only when numpy is not installed.
    samples: list[int] = []
    for chunk in chunks:
        if hasattr(chunk, "detach"):
            chunk = chunk.detach().cpu()
        values = chunk.tolist() if hasattr(chunk, "tolist") else list(chunk)
        for value in values:
            clamped = max(-1.0, min(1.0, float(value)))
            samples.append(int(round(clamped * 32767.0)))
    return struct.pack(f"<{len(samples)}h", *samples)


def _wav_bytes(pcm: bytes) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(KOKORO_SAMPLE_RATE)
        wav_file.writeframes(pcm)
    return buffer.getvalue()


class KokoroEngine:
    """Local neural TTS through the optional `kokoro` package."""

    def __init__(
        self,
        pipeline_factory: Callable[[str], Callable[..., Iterable[Any]]] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        language_getter: Callable[[], str] | None = None,
    ) -> None:
        self._pipeline_factory = pipeline_factory
        self._runner = runner or subprocess.run
        self._language_getter = language_getter or (lambda: speech.get_language())
        self._pipelines: dict[str, Callable[..., Iterable[Any]]] = {}
        self._lock = threading.Lock()
        self._broken = False

    def is_installed(self) -> bool:
        """True when a pipeline factory was injected or the `kokoro` package can be found. Never raises."""
        if self._pipeline_factory is not None:
            return True
        try:
            return importlib.util.find_spec("kokoro") is not None
        except Exception:
            return False

    def usable(self) -> bool:
        """True when Kokoro is installed and has not failed to load earlier in this process."""
        return not self._broken and self.is_installed()

    def _get_pipeline(self, lang_code: str) -> Callable[..., Iterable[Any]]:
        with self._lock:
            pipeline = self._pipelines.get(lang_code)
            if pipeline is not None:
                return pipeline
            if self._broken:
                raise RuntimeError("Kokoro is unavailable.")
            factory = self._pipeline_factory or _default_pipeline_factory
            try:
                pipeline = factory(lang_code)
            except Exception as exc:
                self._broken = True
                logger.warning("Kokoro failed to load (%s).", type(exc).__name__)
                raise RuntimeError("Kokoro pipeline could not be loaded.") from exc
            self._pipelines[lang_code] = pipeline
            return pipeline

    def synthesize(self, text: str, voice: str | None, output_format: str) -> tuple[bytes, str]:
        """Synthesize `text` with Kokoro into `.m4a` (`audio/mp4`) or `.wav` (`audio/wav`)."""
        cleaned, fmt = _validate_request(text, output_format)

        lang = speech.normalize_language(self._language_getter()) or _DEFAULT_LANGUAGE
        chosen_voice = voice.strip() if voice and _KOKORO_VOICE_RE.match(voice.strip()) else _VOICES[lang]

        pipeline = self._get_pipeline(_LANG_CODES[lang])
        chunks: list[Any] = []
        for item in pipeline(cleaned, voice=chosen_voice):
            audio = _audio_of(item)
            if audio is not None:
                chunks.append(audio)
        if not chunks:
            raise RuntimeError("Kokoro produced no audio.")

        pcm = _to_pcm16(chunks)
        if not pcm:
            raise RuntimeError("Kokoro produced no audio.")
        wav_bytes = _wav_bytes(pcm)

        if fmt == "wav":
            return wav_bytes, _FORMAT_MIME_MAP["wav"]
        return self._convert_to_m4a(wav_bytes), _FORMAT_MIME_MAP["m4a"]

    def _convert_to_m4a(self, wav_bytes: bytes) -> bytes:
        with tempfile.TemporaryDirectory(prefix="lupin_kokoro_") as tmp_dir:
            wav_path = Path(tmp_dir) / "speech.wav"
            m4a_path = Path(tmp_dir) / "speech.m4a"
            wav_path.write_bytes(wav_bytes)
            proc = self._runner(
                [_AFCONVERT_BIN, "-f", "m4af", "-d", "aac", str(wav_path), str(m4a_path)],
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0 or not m4a_path.exists():
                raise RuntimeError("Failed to convert Kokoro audio with /usr/bin/afconvert.")
            return m4a_path.read_bytes()


class LupinTTS:
    """Kokoro first, macOS `say` (ServerTTS) as the fallback. Same public interface as ServerTTS."""

    def __init__(self, fallback: ServerTTS, kokoro: KokoroEngine | None = None, enabled: bool = True) -> None:
        self._fallback = fallback
        self._kokoro = kokoro if kokoro is not None else KokoroEngine()
        self._enabled = bool(enabled)
        self._last_engine: str | None = None

    @property
    def default_voice(self) -> str:
        return self._fallback.default_voice

    def _kokoro_ready(self) -> bool:
        return self._enabled and self._kokoro.usable()

    @property
    def engine(self) -> str:
        """`"kokoro"` or `"say"`: the engine of the last successful synthesis, or the one that would be used first."""
        if self._last_engine is not None:
            return self._last_engine
        return "kokoro" if self._kokoro_ready() else "say"

    def is_available(self) -> bool:
        return self._kokoro_ready() or self._fallback.is_available()

    def list_voices(self) -> list[dict[str, str]]:
        return self._fallback.list_voices()

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        output_format: str = "m4a",
    ) -> tuple[bytes, str]:
        _validate_request(text, output_format)  # input errors propagate; they never trigger the fallback
        if self._kokoro_ready():
            try:
                result = self._kokoro.synthesize(text, voice, output_format)
            except Exception as exc:
                logger.warning("Kokoro synthesis failed (%s); falling back to macOS say.", type(exc).__name__)
            else:
                self._last_engine = "kokoro"
                return result
        result = self._fallback.synthesize(text, voice, output_format)
        self._last_engine = "say"
        return result

    async def synthesize_async(
        self,
        text: str,
        voice: str | None = None,
        output_format: str = "m4a",
    ) -> tuple[bytes, str]:
        _validate_request(text, output_format)
        if self._kokoro_ready():
            try:
                result = await asyncio.to_thread(self._kokoro.synthesize, text, voice, output_format)
            except Exception as exc:
                logger.warning("Kokoro synthesis failed (%s); falling back to macOS say.", type(exc).__name__)
            else:
                self._last_engine = "kokoro"
                return result
        result = await self._fallback.synthesize_async(text, voice, output_format)
        self._last_engine = "say"
        return result
