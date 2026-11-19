"""System audio for the Control Deck: output volume, mute, microphone mute.

Volume and mute reuse the whitelisted commands of ``MacController``. The microphone is
muted by setting the input volume to 0 through ``osascript`` with a fixed argv list: no value
from a device is ever put in a script. No per-app audio, no audio drivers (P10 decisions).
"""

from __future__ import annotations

import re
import subprocess
import threading
from collections.abc import Callable
from typing import Any

_OSASCRIPT = "/usr/bin/osascript"
_READ_SETTINGS = "get volume settings"
_DEFAULT_MIC_LEVEL = 75
_VOLUME_COMMANDS = {"up": "volume_up", "down": "volume_down", "mute": "volume_mute"}

Runner = Callable[..., Any]


def parse_volume_settings(text: str) -> dict[str, Any]:
    """Parse ``output volume:50, input volume:75, alert volume:100, output muted:false``."""
    out: dict[str, Any] = {"volume": None, "muted": None, "mic_level": None}
    match = re.search(r"output volume:(\d+)", text or "")
    if match:
        out["volume"] = int(match.group(1))
    match = re.search(r"input volume:(\d+)", text or "")
    if match:
        out["mic_level"] = int(match.group(1))
    match = re.search(r"output muted:(true|false)", text or "")
    if match:
        out["muted"] = match.group(1) == "true"
    return out


class SystemControl:
    """Volume, mute and mic mute. Every method returns a plain dict and never raises."""

    def __init__(self, mac: Any, *, run: Runner | None = None) -> None:
        self._mac = mac
        self._run = run or subprocess.run
        self._lock = threading.Lock()
        self._mic_restore = _DEFAULT_MIC_LEVEL

    def _osascript(self, script: str) -> str | None:
        try:
            proc = self._run(
                [_OSASCRIPT, "-e", script], capture_output=True, text=True, timeout=4.0, check=False
            )
        except Exception:
            return None
        if getattr(proc, "returncode", 1) != 0:
            return None
        return str(getattr(proc, "stdout", "") or "")

    def status(self) -> dict[str, Any]:
        """``{"volume", "muted", "mic_muted"}``; values are None when macOS cannot be read."""
        text = self._osascript(_READ_SETTINGS)
        if text is None:
            return {"volume": None, "muted": None, "mic_muted": None}
        parsed = parse_volume_settings(text)
        mic = parsed["mic_level"]
        return {
            "volume": parsed["volume"],
            "muted": parsed["muted"],
            "mic_muted": None if mic is None else mic == 0,
        }

    def volume(self, op: str) -> dict[str, Any]:
        command = _VOLUME_COMMANDS.get(op)
        if command is None:
            raise ValueError("unknown volume operation")
        result = self._mac.execute_mac_command(command)
        return {"ok": bool(result.get("ok")), **self.status()}

    def mic_toggle(self) -> dict[str, Any]:
        """Mute the microphone, or restore the level it had before. Toggles."""
        with self._lock:
            text = self._osascript(_READ_SETTINGS)
            level = parse_volume_settings(text or "")["mic_level"]
            if level is None:
                return {"ok": False, "mic_muted": None}
            if level > 0:
                self._mic_restore = level
                target = 0
            else:
                target = self._mic_restore or _DEFAULT_MIC_LEVEL
            done = self._osascript(f"set volume input volume {int(target)}")
            return {"ok": done is not None, "mic_muted": target == 0 if done is not None else level == 0}
