"""The only place that runs programs for the image editor.

Every command is a fixed argv list (`/usr/bin/sips`, the Swift compiler, the compiled Vision
helper) run with `subprocess.run` and never a shell. Paths always come from the Brain's own image
store, never from a client. Background removal uses a small Swift helper (`image_helper.swift`,
macOS Vision `VNGenerateForegroundInstanceMaskRequest`) that is compiled once into a cache folder.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import secrets
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SIPS = "/usr/bin/sips"
SWIFTC = "/usr/bin/swiftc"
HELPER_SOURCE = Path(__file__).with_name("image_helper.swift")
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
        self._warmed = False
        self._orient_warned = False
        self._compile_lock = threading.Lock()

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
        result = self._run([str(helper), "cutout", str(src), str(dst)], CUTOUT_TIMEOUT_SECONDS)
        if result.returncode == 4:
            raise ToolError("no_subject")
        if result.returncode == 5:
            raise ToolError("unavailable")
        if result.returncode != 0 or not dst.is_file():
            raise ToolError("edit_failed")

    def normalize_orientation(self, src: Path, dst: Path) -> bool:
        """Bake an EXIF orientation into the pixels (so preview, crop and Vision agree).

        Returns True when `dst` was written, False when the image was already upright or the
        helper is unavailable (the original is then used as is).
        """
        try:
            helper = self._ensure_helper()
            result = self._run([str(helper), "orient", str(src), str(dst)], CUTOUT_TIMEOUT_SECONDS)
        except ToolError as exc:
            if exc.code == "unavailable" and not self._orient_warned:
                self._orient_warned = True
                logger.warning("Image helper unavailable; EXIF rotation was not normalised.")
            return False
        return result.returncode == 0 and dst.is_file()

    def strip_gps(self, src: Path, dst: Path) -> None:
        """Copy an image without its GPS/location metadata, keeping the other metadata.

        Raises ToolError so a JPEG or HEIC with unknown contents is never saved with a location.
        """
        helper = self._ensure_helper()
        result = self._run([str(helper), "stripgps", str(src), str(dst)], CUTOUT_TIMEOUT_SECONDS)
        if result.returncode != 0 or not dst.is_file():
            raise ToolError("edit_failed")

    def _ensure_helper(self) -> Path:
        """Compile the helper once into the cache folder; unavailable when that fails."""
        helper = self._cache_dir / "image_helper"
        if helper.is_file():
            return helper
        if self._helper_failed or not self._helper_source.is_file():
            raise ToolError("unavailable")
        with self._compile_lock:
            if helper.is_file():
                return helper
            self._cache_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            with contextlib.suppress(OSError):
                self._cache_dir.chmod(0o700)
            partial = self._cache_dir / f"image_helper.{secrets.token_hex(4)}.tmp"
            try:
                result = self._run(
                    [self._swiftc, "-O", str(self._helper_source), "-o", str(partial)],
                    COMPILE_TIMEOUT_SECONDS,
                )
                if result.returncode != 0 or not partial.is_file():
                    self._helper_failed = True
                    logger.warning("Image helper could not be compiled; Vision features unavailable.")
                    raise ToolError("unavailable")
                os.replace(partial, helper)
            except ToolError:
                raise
            finally:
                with contextlib.suppress(OSError):
                    partial.unlink()
        return helper

    def warm_up(self) -> None:
        """Compile the helper in the background so the first upload does not wait for it.

        Runs at most once. Never called from register(): a Panel's first look at the editor
        (GET /api/images/last) starts it.
        """
        if self._warmed:
            return
        self._warmed = True
        threading.Thread(target=self._warm, daemon=True).start()

    def _warm(self) -> None:
        with contextlib.suppress(ToolError):
            self._ensure_helper()


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value or "")
