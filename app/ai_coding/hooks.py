"""Install and remove the Claude Code hooks that talk to the Brain (opt-in, Mac only).

The hooks are three `curl` commands in Claude Code's settings file that POST to the Brain on
127.0.0.1. Installing remembers the original file bytes; removing puts them back exactly when the
file is still what we wrote, and otherwise removes only our entries. Paths are injectable.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

MARKER = "/api/claude-hooks/"
EVENTS = {
    "PermissionRequest": ("permission", 125),
    "Notification": ("event", 6),
    "Stop": ("event", 6),
}


class HooksError(Exception):
    """A readable reason the settings file could not be changed."""


def _is_ours(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    return any(
        isinstance(h, dict) and MARKER in str(h.get("command", "")) for h in entry.get("hooks", [])
    )


class HooksInstaller:
    def __init__(self, settings_path: Path, state_path: Path, port: int) -> None:
        self.settings_path = Path(settings_path)
        self.state_path = Path(state_path)
        self.port = int(port)

    def _command(self, route: str, seconds: int) -> str:
        url = f"http://127.0.0.1:{self.port}{MARKER}{route}"
        return (
            f"curl -s -m {seconds} -X POST -H 'Content-Type: application/json' "
            f"--data-binary @- {url} || true"
        )

    def entries(self) -> dict[str, list[dict[str, Any]]]:
        """Exactly what install adds, per event."""
        return {
            event: [
                {"hooks": [{"type": "command", "command": self._command(route, seconds), "timeout": seconds + 5}]}
            ]
            for event, (route, seconds) in EVENTS.items()
        }

    def _read(self) -> tuple[str | None, dict[str, Any]]:
        if not self.settings_path.exists():
            return None, {}
        try:
            text = self.settings_path.read_bytes().decode("utf-8")
            data = json.loads(text) if text.strip() else {}
        except (OSError, ValueError) as exc:
            raise HooksError("Claude Code's settings file is not valid JSON; nothing was changed.") from exc
        if not isinstance(data, dict):
            raise HooksError("Claude Code's settings file is not a JSON object; nothing was changed.")
        return text, data

    def _write(self, text: str) -> None:
        self.settings_path.parent.mkdir(parents=True, exist_ok=True)
        mode = self.settings_path.stat().st_mode & 0o777 if self.settings_path.exists() else 0o600
        fd, tmp = tempfile.mkstemp(dir=str(self.settings_path.parent), prefix=".settings-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            os.chmod(tmp, mode)
            os.replace(tmp, self.settings_path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    def status(self) -> dict[str, Any]:
        _text, data = self._read()
        hooks = data.get("hooks") if isinstance(data.get("hooks"), dict) else {}
        present = [e for e in EVENTS if any(_is_ours(x) for x in hooks.get(e, []))]
        return {
            "installed": len(present) == len(EVENTS),
            "events": present,
            "settings_file": str(self.settings_path),
            "adds": self.entries(),
        }

    def install(self) -> dict[str, Any]:
        original, data = self._read()
        hooks = data.setdefault("hooks", {})
        if not isinstance(hooks, dict):
            raise HooksError("Claude Code's settings have an unexpected 'hooks' value; nothing was changed.")
        for event, entries in self.entries().items():
            existing = hooks.setdefault(event, [])
            if not isinstance(existing, list):
                raise HooksError("Claude Code's settings have an unexpected hook list; nothing was changed.")
            if not any(_is_ours(x) for x in existing):
                existing.extend(copy.deepcopy(entries))
        written = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        if written == original:
            return self.status()
        if not self.state_path.exists():
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(
                    {
                        "original": original,
                        "existed": original is not None,
                        "written_sha": hashlib.sha256(written.encode("utf-8")).hexdigest(),
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(self.state_path, 0o600)
        else:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
            state["written_sha"] = hashlib.sha256(written.encode("utf-8")).hexdigest()
            self.state_path.write_text(json.dumps(state), encoding="utf-8")
        self._write(written)
        return self.status()

    def remove(self) -> dict[str, Any]:
        state = None
        if self.state_path.exists():
            try:
                state = json.loads(self.state_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                state = None
        if isinstance(state, dict) and self.settings_path.exists():
            current = self.settings_path.read_bytes()
            if hashlib.sha256(current).hexdigest() == state.get("written_sha"):
                if state.get("existed") and isinstance(state.get("original"), str):
                    self._write(state["original"])
                else:
                    self.settings_path.unlink()
                self.state_path.unlink(missing_ok=True)
                return self.status()
        # Edited since we wrote it (or no backup): take out only our own entries.
        if self.settings_path.exists():
            _text, data = self._read()
            hooks = data.get("hooks")
            if isinstance(hooks, dict):
                for event in list(hooks):
                    if isinstance(hooks[event], list):
                        hooks[event] = [x for x in hooks[event] if not _is_ours(x)]
                        if not hooks[event]:
                            del hooks[event]
                if not hooks:
                    del data["hooks"]
                self._write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        self.state_path.unlink(missing_ok=True)
        return self.status()
