"""The only place that runs programs for the image editor.

Every command is a fixed argv list (`/usr/bin/sips`, the Swift compiler, the compiled Vision
helper) run with `subprocess.run` and never a shell. Paths always come from the Brain's own image
store, never from a client. Background removal uses a small Swift helper (`vision_cutout.swift`,
macOS Vision `VNGenerateForegroundInstanceMaskRequest`) that is compiled once into a cache folder.
"""

from __future__ import annotations

import logging
import re
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SIPS = "/usr/bin/sips"
SWIFTC = "/usr/bin/swiftc"
HELPER_SOURCE = Path(__file__).with_name("vision_cutout.swift")
SIPS_TIMEOUT_SECONDS = 60
COMPILE_TIMEOUT_SECONDS = 240
CUTOUT_TIMEOUT_SECONDS = 120

# User-facing format name -> (sips format name, file extension). WebP can be read but not written.
OUTPUT_FORMATS: dict[str, tuple[str, str]] = {
    "heic": ("heic", "heic"),
    "png": ("png", "png"),
    "jpg": ("jpeg", "jpg"),
    "jpeg": ("jpeg", "jpg"),
}

_DIMENSION_RE = re.compile(r"pixel(Width|Height):\s*(\d+)")


class ToolError(Exception):
    """An edit failed. `code` is one of: unavailable, no_subject, edit_failed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ImageTools:
    """Fixed-argv wrappers around sips and the Vision cutout helper."""

    def __init__(
        self,
        cache_dir: Path,
        *,
        run: Callable[..., Any] = subprocess.run,
        sips: str = SIPS,
        swiftc: str = SWIFTC,
        helper_source: Path = HELPER_SOURCE,
    ) -> None:
        self._cache_dir = Path(cache_dir)
        self._run_impl = run
        self._sips = sips
        self._swiftc = swiftc
        self._helper_source = helper_source
        self._helper_failed = False

    def _run(self, argv: list[str], timeout: int) -> Any:
        try:
            return self._run_impl(argv, capture_output=True, timeout=timeout, check=False)
        except FileNotFoundError as exc:
            raise ToolError("unavailable") from exc
        except subprocess.TimeoutExpired as exc:
            raise ToolError("edit_failed") from exc
        except OSError as exc:
            raise ToolError("edit_failed") from exc

    def _sips_ok(self, args: list[str], src: Path, dst: Path) -> None:
        result = self._run([self._sips, *args, str(src), "--out", str(dst)], SIPS_TIMEOUT_SECONDS)
        if result.returncode != 0 or not dst.is_file():
            raise ToolError("edit_failed")

    def dimensions(self, path: Path) -> tuple[int, int] | None:
        """Pixel size of an image, or None when sips cannot read it."""
        try:
            result = self._run(
                [self._sips, "-g", "pixelWidth", "-g", "pixelHeight", str(path)], SIPS_TIMEOUT_SECONDS
            )
        except ToolError:
            return None
        if result.returncode != 0:
            return None
        found = {key: int(value) for key, value in _DIMENSION_RE.findall(_text(result.stdout))}
        if "Width" in found and "Height" in found and found["Width"] > 0 and found["Height"] > 0:
            return found["Width"], found["Height"]
        return None

    def crop(self, src: Path, dst: Path, left: int, top: int, width: int, height: int) -> None:
        self._sips_ok(
            ["-c", str(height), str(width), "--cropOffset", str(top), str(left)], src, dst
        )

    def resize(self, src: Path, dst: Path, width: int | None, height: int | None) -> None:
        if width and height:
            args = ["--resampleHeightWidthMax", str(height), str(width)]
        elif width:
            args = ["--resampleWidth", str(width)]
        elif height:
            args = ["--resampleHeight", str(height)]
        else:
            raise ToolError("edit_failed")
        self._sips_ok(args, src, dst)

    def convert(self, src: Path, dst: Path, fmt: str, quality: int | None = None) -> None:
        if fmt not in OUTPUT_FORMATS:
            raise ToolError("unavailable")
        args = ["-s", "format", OUTPUT_FORMATS[fmt][0]]
        if quality is not None:
            args += ["-s", "formatOptions", str(int(quality))]
        self._sips_ok(args, src, dst)

    def remove_background(self, src: Path, dst: Path) -> None:
        helper = self._ensure_helper()
        result = self._run([str(helper), str(src), str(dst)], CUTOUT_TIMEOUT_SECONDS)
        if result.returncode == 4:
            raise ToolError("no_subject")
        if result.returncode == 5:
            raise ToolError("unavailable")
        if result.returncode != 0 or not dst.is_file():
            raise ToolError("edit_failed")

    def _ensure_helper(self) -> Path:
        """Compile the Vision helper once into the cache folder; unavailable when that fails."""
        helper = self._cache_dir / "vision_cutout"
        if helper.is_file():
            return helper
        if self._helper_failed or not self._helper_source.is_file():
            raise ToolError("unavailable")
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        result = self._run(
            [self._swiftc, "-O", str(self._helper_source), "-o", str(helper)],
            COMPILE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0 or not helper.is_file():
            self._helper_failed = True
            logger.warning("Vision helper could not be compiled; background removal unavailable.")
            raise ToolError("unavailable")
        return helper


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value or "")
