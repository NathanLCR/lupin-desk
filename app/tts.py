"""Síntese de voz (TTS) offline no macOS via `/usr/bin/say` e `/usr/bin/afconvert`."""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SAY_BIN = "/usr/bin/say"
_AFCONVERT_BIN = "/usr/bin/afconvert"

_VOICE_LINE_RE = re.compile(r"^(.+?)\s{2,}([a-zA-Z]{2,3}_[A-Za-z0-9_]+)\s+#\s*(.*)$")
_SAFE_VOICE_RE = re.compile(r"^[A-Za-z0-9À-ÿ ._()-]{1,64}$")

_FORMAT_MIME_MAP: dict[str, str] = {
    "m4a": "audio/mp4",
    "wav": "audio/wav",
}


class ServerTTS:
    """Sintetizador de voz offline no servidor macOS para iPhone Safari e Android."""

    def __init__(
        self,
        default_voice: str = "Luciana",
        synth_fn: Callable[..., Any] | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.default_voice = (default_voice or "Luciana").strip() or "Luciana"
        self._synth_fn = synth_fn
        self._runner = runner or subprocess.run

    def is_available(self) -> bool:
        """Indica se o backend de síntese está disponível no ambiente."""
        if self._synth_fn is not None:
            return True
        return Path(_SAY_BIN).exists() and Path(_AFCONVERT_BIN).exists()

    def list_voices(self) -> list[dict[str, str]]:
        """Lista vozes disponíveis no macOS priorizando português (PT-BR / PT-PT)."""
        if not Path(_SAY_BIN).exists() and self._runner is subprocess.run:
            return []

        try:
            proc = self._runner(
                [_SAY_BIN, "-v", "?"],
                shell=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception as exc:
            logger.warning("Não foi possível listar vozes do sistema (%s).", type(exc).__name__)
            return []

        if proc.returncode != 0:
            return []

        voices: list[dict[str, str]] = []
        for raw_line in (proc.stdout or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            match = _VOICE_LINE_RE.match(line)
            if not match:
                continue
            name = match.group(1).strip()
            locale = match.group(2).strip()
            sample = match.group(3).strip()
            voices.append({"name": name, "locale": locale, "sample": sample})

        def _sort_key(item: dict[str, str]) -> tuple[int, str]:
            locale_lower = item["locale"].lower()
            if locale_lower == "pt_br":
                return (0, item["name"].lower())
            if locale_lower.startswith("pt_"):
                return (1, item["name"].lower())
            return (2, item["name"].lower())

        voices.sort(key=_sort_key)
        return voices

    def synthesize(
        self,
        text: str,
        voice: str | None = None,
        output_format: str = "m4a",
    ) -> tuple[bytes, str]:
        """Sintetiza texto em áudio `.m4a` (`audio/mp4`) ou `.wav` (`audio/wav`)."""
        cleaned_text = " ".join((text or "").split())
        if not cleaned_text:
            raise ValueError("Texto não pode ser vazio para síntese de voz.")

        fmt = (output_format or "m4a").strip().lower()
        if fmt not in _FORMAT_MIME_MAP:
            raise ValueError(f"Formato de áudio não suportado: {fmt}. Use 'm4a' ou 'wav'.")
        mime_type = _FORMAT_MIME_MAP[fmt]

        chosen_voice = (voice if voice is not None else self.default_voice).strip()
        if chosen_voice and not _SAFE_VOICE_RE.match(chosen_voice):
            raise ValueError("Nome de voz inválido.")

        if self._synth_fn is not None:
            result = self._synth_fn(cleaned_text, chosen_voice or self.default_voice, fmt)
            if isinstance(result, tuple) and len(result) == 2:
                return bytes(result[0]), str(result[1])
            return bytes(result), mime_type

        if not (Path(_SAY_BIN).exists() and Path(_AFCONVERT_BIN).exists()) and self._runner is subprocess.run:
            raise RuntimeError("TTS do servidor disponível apenas no macOS com /usr/bin/say e afconvert.")

        with tempfile.TemporaryDirectory(prefix="desk_tts_") as tmp_dir:
            tmp_root = Path(tmp_dir)
            text_path = tmp_root / "input.txt"
            aiff_path = tmp_root / "speech.aiff"
            out_path = tmp_root / f"speech.{fmt}"
            text_path.write_text(cleaned_text, encoding="utf-8")

            say_argv = [_SAY_BIN]
            if chosen_voice:
                say_argv.extend(["-v", chosen_voice])
            say_argv.extend(["-f", str(text_path), "-o", str(aiff_path)])

            say_proc = self._runner(
                say_argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if say_proc.returncode != 0 and chosen_voice:
                logger.warning("Voz '%s' indisponível no macOS; usando voz padrão do sistema.", chosen_voice)
                say_proc = self._runner(
                    [_SAY_BIN, "-f", str(text_path), "-o", str(aiff_path)],
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )

            if say_proc.returncode != 0:
                raise RuntimeError("Falha ao gerar áudio com /usr/bin/say.")

            if fmt == "m4a":
                convert_argv = [
                    _AFCONVERT_BIN,
                    "-f",
                    "m4af",
                    "-d",
                    "aac",
                    str(aiff_path),
                    str(out_path),
                ]
            else:
                convert_argv = [
                    _AFCONVERT_BIN,
                    "-f",
                    "WAVE",
                    "-d",
                    "LEI16@16000",
                    "-c",
                    "1",
                    str(aiff_path),
                    str(out_path),
                ]

            conv_proc = self._runner(
                convert_argv,
                shell=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if conv_proc.returncode != 0 or not out_path.exists():
                raise RuntimeError("Falha ao converter áudio com /usr/bin/afconvert.")

            return out_path.read_bytes(), mime_type

    async def synthesize_async(
        self,
        text: str,
        voice: str | None = None,
        output_format: str = "m4a",
    ) -> tuple[bytes, str]:
        """Versão assíncrona de `synthesize` executada em thread dedicada."""
        if self._synth_fn is not None and inspect.iscoroutinefunction(self._synth_fn):
            cleaned_text = " ".join((text or "").split())
            if not cleaned_text:
                raise ValueError("Texto não pode ser vazio para síntese de voz.")
            fmt = (output_format or "m4a").strip().lower()
            if fmt not in _FORMAT_MIME_MAP:
                raise ValueError(f"Formato de áudio não suportado: {fmt}. Use 'm4a' ou 'wav'.")
            chosen_voice = (voice if voice is not None else self.default_voice).strip()
            if chosen_voice and not _SAFE_VOICE_RE.match(chosen_voice):
                raise ValueError("Nome de voz inválido.")
            res = await self._synth_fn(cleaned_text, chosen_voice or self.default_voice, fmt)
            if isinstance(res, tuple) and len(res) == 2:
                return bytes(res[0]), str(res[1])
            return bytes(res), _FORMAT_MIME_MAP[fmt]

        return await asyncio.to_thread(self.synthesize, text, voice, output_format)
