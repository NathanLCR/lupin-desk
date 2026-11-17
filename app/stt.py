"""Local audio transcription (STT) with lazy loading and a safe fallback."""

from __future__ import annotations

import asyncio
import importlib.util
import inspect
import logging
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_AFCONVERT_BIN = "/usr/bin/afconvert"

_MIME_EXTENSION_MAP: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/caf": ".caf",
    "audio/x-caf": ".caf",
}

_AFCONVERT_COMPATIBLE_EXTS: frozenset[str] = frozenset(
    {".m4a", ".mp4", ".aac", ".caf", ".aiff", ".aif", ".wav"}
)


def _extension_for_mime(mime_type: str) -> str:
    """Resolve the temporary file extension from the given MIME type."""
    cleaned = (mime_type or "").split(";", 1)[0].strip().lower()
    return _MIME_EXTENSION_MAP.get(cleaned, ".webm")


class LocalSTT:
    """Local transcription engine (Speech-to-Text) supporting faster-whisper and mlx-whisper."""

    def __init__(
        self,
        model_name: str = "base",
        language: str = "pt",
        transcribe_fn: Callable[..., Any] | None = None,
    ) -> None:
        self.model_name = (model_name or "base").strip() or "base"
        self.language = (language or "pt").strip() or "pt"
        self._transcribe_fn = transcribe_fn
        self._model_lock = threading.Lock()
        self._fw_model: Any = None
        self._mlx_module: Any = None

    def _detect_engine(self) -> str:
        """Detect the available backend without loading weights at startup."""
        if self._transcribe_fn is not None:
            return "custom"
        if importlib.util.find_spec("mlx_whisper") is not None:
            return "mlx-whisper"
        if importlib.util.find_spec("faster_whisper") is not None:
            return "faster-whisper"
        return "unavailable"

    def is_available(self) -> bool:
        """Report whether at least one transcription engine is available."""
        return self._detect_engine() != "unavailable"

    def status(self) -> dict[str, Any]:
        """Return the current STT engine state for diagnostics."""
        engine = self._detect_engine()
        return {
            "available": engine != "unavailable",
            "engine": engine,
            "model": self.model_name,
            "language": self.language,
            "loaded": (self._fw_model is not None) or (self._mlx_module is not None),
        }

    def _get_faster_whisper_model(self) -> Any:
        """Load the faster-whisper model on demand (lazy load)."""
        with self._model_lock:
            if self._fw_model is None:
                from faster_whisper import WhisperModel  # type: ignore[import-not-found]

                self._fw_model = WhisperModel(
                    self.model_name,
                    device="cpu",
                    compute_type="int8",
                )
            return self._fw_model

    def _get_mlx_whisper_module(self) -> Any:
        """Import mlx_whisper on demand."""
        with self._model_lock:
            if self._mlx_module is None:
                import mlx_whisper  # type: ignore[import-not-found]

                self._mlx_module = mlx_whisper
            return self._mlx_module

    def _convert_to_wav(self, src_path: Path, dst_wav_path: Path) -> Path:
        """Convert input audio to 16 kHz mono WAV using PyAV or afconvert."""
        if src_path.suffix.lower() == ".wav":
            return src_path

        # 1) Try decoding via PyAV (`av`) to support WebM/Opus without ffmpeg.
        if importlib.util.find_spec("av") is not None:
            try:
                import av  # type: ignore[import-not-found]

                with av.open(str(src_path)) as in_container:
                    audio_stream = next(
                        (s for s in in_container.streams if s.type == "audio"),
                        None,
                    )
                    if audio_stream is not None:
                        resampler = av.AudioResampler(
                            format="s16",
                            layout="mono",
                            rate=16000,
                        )
                        with av.open(str(dst_wav_path), mode="w", format="wav") as out_container:
                            out_stream = out_container.add_stream("pcm_s16le", rate=16000)
                            out_stream.layout = "mono"
                            for frame in in_container.decode(audio_stream):
                                for resampled in resampler.resample(frame):
                                    for packet in out_stream.encode(resampled):
                                        out_container.mux(packet)
                            for packet in out_stream.encode(None):
                                out_container.mux(packet)
                        if dst_wav_path.exists() and dst_wav_path.stat().st_size > 44:
                            return dst_wav_path
            except Exception as exc:
                logger.warning("PyAV conversion failed (%s); trying afconvert.", type(exc).__name__)

        # 2) Native macOS fallback via /usr/bin/afconvert (never uses shell=True).
        if (
            src_path.suffix.lower() in _AFCONVERT_COMPATIBLE_EXTS
            and Path(_AFCONVERT_BIN).exists()
        ):
            proc = subprocess.run(
                [
                    _AFCONVERT_BIN,
                    "-f",
                    "WAVE",
                    "-d",
                    "LEI16@16000",
                    "-c",
                    "1",
                    str(src_path),
                    str(dst_wav_path),
                ],
                shell=False,
                capture_output=True,
                text=True,
                timeout=20,
            )
            if proc.returncode == 0 and dst_wav_path.exists():
                return dst_wav_path

        return src_path

    def _transcribe_sync(
        self,
        audio_bytes: bytes,
        mime_type: str,
        language: str,
    ) -> dict[str, Any]:
        """Run local transcription in a dedicated thread."""
        engine = self._detect_engine()
        if engine == "unavailable":
            return {
                "text": "",
                "available": False,
                "engine": "unavailable",
                "error": (
                    "Local transcription unavailable: install faster-whisper or mlx-whisper "
                    "in the virtual environment."
                ),
            }

        ext = _extension_for_mime(mime_type)
        with tempfile.TemporaryDirectory(prefix="desk_stt_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            src_path = tmp_root / f"input{ext}"
            wav_path = tmp_root / "converted.wav"
            src_path.write_bytes(audio_bytes)
            target_path = self._convert_to_wav(src_path, wav_path)

            if engine == "mlx-whisper":
                mlx_mod = self._get_mlx_whisper_module()
                repo = f"mlx-community/whisper-{self.model_name}-mlx"
                result = mlx_mod.transcribe(
                    str(target_path),
                    path_or_hf_repo=repo,
                    language=language,
                )
                text = str((result or {}).get("text") or "").strip()
                return {
                    "text": text,
                    "available": True,
                    "engine": "mlx-whisper",
                    "error": None,
                }

            model = self._get_faster_whisper_model()
            segments, _info = model.transcribe(
                str(target_path),
                language=language,
                vad_filter=True,
            )
            text = " ".join(str(getattr(seg, "text", "")).strip() for seg in segments).strip()
            return {
                "text": text,
                "available": True,
                "engine": "faster-whisper",
                "error": None,
            }

    async def transcribe_bytes(
        self,
        audio_bytes: bytes,
        mime_type: str = "audio/webm",
        language: str = "pt",
    ) -> dict[str, Any]:
        """Transcribe audio bytes asynchronously, returning a standardized payload."""
        lang = (language or self.language or "pt").strip() or "pt"
        engine = self._detect_engine()

        if not audio_bytes:
            return {
                "text": "",
                "available": engine != "unavailable",
                "engine": engine,
                "error": "No audio received for transcription.",
            }

        if self._transcribe_fn is not None:
            try:
                result = self._transcribe_fn(audio_bytes, mime_type, lang)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, dict):
                    return {
                        "text": str(result.get("text") or "").strip(),
                        "available": bool(result.get("available", True)),
                        "engine": str(result.get("engine") or "custom"),
                        "error": result.get("error"),
                    }
                return {
                    "text": str(result or "").strip(),
                    "available": True,
                    "engine": "custom",
                    "error": None,
                }
            except Exception as exc:
                logger.error("Error in custom STT function: %s", type(exc).__name__)
                return {
                    "text": "",
                    "available": True,
                    "engine": "custom",
                    "error": "Failed to transcribe the received audio.",
                }

        try:
            return await asyncio.to_thread(self._transcribe_sync, audio_bytes, mime_type, lang)
        except Exception as exc:
            logger.error("Local transcription error (%s)", type(exc).__name__)
            return {
                "text": "",
                "available": engine != "unavailable",
                "engine": engine,
                "error": f"Local transcription failed ({type(exc).__name__}).",
            }
