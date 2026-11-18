"""Safe macOS control via whitelisted argv, Live Dock, status and weather."""

from __future__ import annotations

import inspect
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import httpx

DEFAULT_FAVORITE_APPS: tuple[str, ...] = (
    "Finder",
    "Google Chrome",
    "Safari",
    "Terminal",
    "Visual Studio Code",
    "Notes",
    "Spotify",
)

# Strict regex for macOS app names (blocks shell/script metacharacters)
_APP_NAME_RE = re.compile(r"^[A-Za-z0-9À-ÿ ._+-]{1,80}$")

# Closed whitelist of modifiers and keys allowed for keystrokes
_MODIFIER_MAP: dict[str, str] = {
    "cmd": "command down",
    "command": "command down",
    "opt": "option down",
    "option": "option down",
    "alt": "option down",
    "ctrl": "control down",
    "control": "control down",
    "shift": "shift down",
}

_MODIFIER_CANONICAL_ORDER: tuple[str, ...] = (
    "command down",
    "option down",
    "control down",
    "shift down",
)

_SPECIAL_KEY_CODES: dict[str, int] = {
    "left": 123,
    "right": 124,
    "down": 125,
    "up": 126,
    "tab": 48,
    "space": 49,
    "return": 36,
    "enter": 36,
    "esc": 53,
    "escape": 53,
    "delete": 51,
    "backspace": 51,
    "forwarddelete": 117,
    "home": 115,
    "end": 119,
    "pageup": 116,
    "pagedown": 121,
    "grave": 50,
    "`": 50,
    "minus": 27,
    "-": 27,
    "equal": 24,
    "=": 24,
    "comma": 43,
    ",": 43,
    "period": 47,
    ".": 47,
    "slash": 44,
    "/": 44,
    "semicolon": 41,
    ";": 41,
    "quote": 39,
    "'": 39,
    "lbracket": 33,
    "[": 33,
    "rbracket": 30,
    "]": 30,
    "backslash": 42,
    "\\": 42,
    "f1": 122,
    "f2": 120,
    "f3": 99,
    "f4": 118,
    "f5": 96,
    "f6": 97,
    "f7": 98,
    "f8": 100,
    "f9": 101,
    "f10": 109,
    "f11": 103,
    "f12": 111,
}

_SINGLE_ALNUM_RE = re.compile(r"^[a-z0-9]$")

VALID_MAC_COMMANDS: frozenset[str] = frozenset(
    {
        "mission_control",
        "app_expose",
        "space_left",
        "space_right",
        "screenshot_clipboard",
        "screenshot_area_file",
        "screenshot_file",
        "screenshot_full",
        "play_pause",
        "next_track",
        "prev_track",
        "volume_up",
        "volume_down",
        "volume_mute",
        "lock_screen",
        "toggle_dock",
        "pomodoro_start",
        "pomodoro_stop",
    }
)

_ACCESSIBILITY_ERROR_MARKERS: tuple[str, ...] = (
    "1002",
    "not allowed to send keystrokes",
    "assistive access",
    "accessibility",
    "acessibilidade",
)

_LIST_APPS_SCRIPT = """
tell application "System Events"
    set outputLines to {}
    repeat with proc in (every application process whose background only is false)
        set procName to name of proc
        set isFront to frontmost of proc
        set end of outputLines to procName & "||" & (isFront as text)
    end repeat
    set AppleScript's text item delimiters to linefeed
    return outputLines as text
end tell
""".strip()

_STATUS_CACHE_TTL_SECONDS = 3.0
_WEATHER_CACHE_TTL_SECONDS = 900.0

# Clipboard paste (dictation): absolute binaries only, text travels through stdin.
_PBPASTE_BIN = "/usr/bin/pbpaste"
_PBCOPY_BIN = "/usr/bin/pbcopy"
_PASTE_MAX_CHARS = 20000
# Time the target app gets to read the clipboard before the previous one is restored.
_PASTE_SETTLE_SECONDS = 0.15


# Today's calendar (read-only): one line per event with
# "seconds since midnight<TAB>true/false (all day)<TAB>title".
_CALENDAR_TODAY_SCRIPT = """
set todayStart to current date
set time of todayStart to 0
set tomorrowStart to todayStart + (1 * days)
set outputText to ""
tell application "Calendar"
    repeat with cal in calendars
        set todayEvents to (every event of cal whose start date ≥ todayStart and start date < tomorrowStart)
        repeat with ev in todayEvents
            set startOffset to ((start date of ev) - todayStart) as integer
            set outputText to outputText & startOffset & tab & ((allday event of ev) as string) & tab & (summary of ev) & linefeed
        end repeat
    end repeat
end tell
return outputText
"""


def parse_calendar_output(stdout: str) -> list[dict[str, Any]]:
    """Convert the Calendar script output into events sorted by time."""
    events: list[tuple[int, dict[str, Any]]] = []
    for line in (stdout or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        try:
            seconds = int(parts[0].strip())
        except ValueError:
            continue
        title = " ".join(p.strip() for p in parts[2:] if p.strip())
        if not title or not 0 <= seconds < 86400:
            continue
        events.append(
            (
                seconds,
                {
                    "start": f"{seconds // 3600:02d}:{seconds % 3600 // 60:02d}",
                    "title": title[:120],
                    "all_day": parts[1].strip().lower() == "true",
                },
            )
        )
    events.sort(key=lambda item: item[0])
    return [ev for _, ev in events]


# Mail.app inbox (read-only): the first line is the unread count of the unified inbox
# (all accounts); the rest are "sender<TAB>subject" of unread messages from the last 24h
# (newest first, at most 10; only looks at the 300 newest messages). Never reads the body or alters messages.
_MAIL_INBOX_SCRIPT = """
set outputText to ""
tell application "Mail"
    set outputText to ((unread count of inbox) as string) & linefeed
    set cutoff to (current date) - (1 * days)
    set foundCount to 0
    set inboxMessages to messages of inbox
    set messageCount to count of inboxMessages
    if messageCount > 300 then set messageCount to 300
    repeat with i from 1 to messageCount
        set m to item i of inboxMessages
        if (date received of m) < cutoff then exit repeat
        if read status of m is false then
            set outputText to outputText & (sender of m) & tab & (subject of m) & linefeed
            set foundCount to foundCount + 1
            if foundCount ≥ 10 then exit repeat
        end if
    end repeat
end tell
return outputText
"""


def parse_mail_output(stdout: str) -> dict[str, Any] | None:
    """Convert the Mail.app script output into an unread count and recent items.

    Returns None if the first line is not a valid count.
    """
    lines = (stdout or "").splitlines()
    if not lines:
        return None
    try:
        unread = int(lines[0].strip())
    except ValueError:
        return None
    if unread < 0:
        return None
    recent: list[dict[str, str]] = []
    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        sender = parts[0].strip()
        subject = " ".join(p.strip() for p in parts[1:] if p.strip())
        if not sender and not subject:
            continue
        recent.append({"sender": sender[:80], "subject": subject[:120]})
        if len(recent) >= 10:
            break
    return {"unread": unread, "recent": recent}


def _is_accessibility_error(stderr: str) -> bool:
    """Detect macOS Accessibility permission errors in the `osascript` stderr."""
    lowered = (stderr or "").lower()
    return any(marker in lowered for marker in _ACCESSIBILITY_ERROR_MARKERS)


def _interpret_weather_code(code: int | None) -> tuple[str, str]:
    """Translate an Open-Meteo WMO code into a description and a visual effect."""
    if code is None:
        return ("Unknown", "none")
    if code == 0:
        return ("Clear sky", "sun")
    if code in {1, 2}:
        return ("Partly cloudy", "sun")
    if code in {3, 45, 48}:
        return ("Cloudy", "none")
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99}:
        return ("Rain", "rain")
    if code in {71, 73, 75, 77, 85, 86}:
        return ("Snow", "snow")
    return ("Variable", "none")


class MacController:
    """Safe executor of macOS commands using only `argv` lists."""

    def __init__(
        self,
        runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
        weather_fetcher: Callable[..., dict[str, Any]] | None = None,
    ) -> None:
        self._custom_runner = runner
        self._weather_fetcher = weather_fetcher
        self._lock = threading.RLock()
        self._status_cache: tuple[float, dict[str, Any]] | None = None
        self._weather_cache: dict[tuple[float, float, str], tuple[float, dict[str, Any]]] = {}
        self._pomodoro_state: dict[str, Any] = {
            "active": False,
            "duration_minutes": 25,
            "started_at": None,
        }

    @staticmethod
    def _default_runner(
        argv: list[str], timeout: float = 5.0, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run an external process without a shell (`shell=False`) and with a timeout."""
        return subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            input=input_text,
        )

    def _run_cmd(
        self, argv: list[str], timeout: float = 5.0, input_text: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Dispatch execution to the default runner or a mock injected in tests."""
        try:
            if self._custom_runner is None:
                if input_text is None:
                    return self._default_runner(argv, timeout=timeout)
                return self._default_runner(argv, timeout=timeout, input_text=input_text)

            try:
                sig = inspect.signature(self._custom_runner)
                accepts_timeout = "timeout" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
                accepts_input = "input_text" in sig.parameters or any(
                    p.kind == inspect.Parameter.VAR_KEYWORD
                    for p in sig.parameters.values()
                )
            except (TypeError, ValueError):
                accepts_timeout = False
                accepts_input = False

            kwargs: dict[str, Any] = {}
            if accepts_timeout:
                kwargs["timeout"] = timeout
            if input_text is not None and accepts_input:
                kwargs["input_text"] = input_text
            return self._custom_runner(argv, **kwargs)
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=124,
                stdout="",
                stderr="Timed out while running the command.",
            )
        except OSError as exc:
            return subprocess.CompletedProcess(
                args=argv,
                returncode=1,
                stdout="",
                stderr=str(exc),
            )

    def read_today_calendar(self) -> list[dict[str, Any]] | None:
        """Read today's events from Calendar.app (read-only). None if it cannot be read."""
        proc = self._run_cmd(["/usr/bin/osascript", "-e", _CALENDAR_TODAY_SCRIPT], timeout=8.0)
        if proc.returncode != 0:
            return None
        return parse_calendar_output(proc.stdout)

    def read_inbox(self) -> dict[str, Any] | None:
        """Read the Mail.app inbox (read-only). None if it cannot be read."""
        proc = self._run_cmd(["/usr/bin/osascript", "-e", _MAIL_INBOX_SCRIPT], timeout=15.0)
        if proc.returncode != 0:
            return None
        return parse_mail_output(proc.stdout)

    def list_running_apps(self) -> list[dict[str, Any]]:
        """List the apps open on the Mac (frontmost highlighted) plus the default favorites."""
        proc = self._run_cmd(["/usr/bin/osascript", "-e", _LIST_APPS_SCRIPT], timeout=4.0)

        running_entries: list[dict[str, Any]] = []
        seen_lower: set[str] = set()
        favorites_lower = {name.lower() for name in DEFAULT_FAVORITE_APPS}

        if proc.returncode == 0 and proc.stdout:
            for raw_line in proc.stdout.splitlines():
                line = raw_line.strip()
                if not line or "||" not in line:
                    continue
                name_part, front_part = line.rsplit("||", 1)
                app_name = name_part.strip()
                if not app_name:
                    continue
                key = app_name.lower()
                if key in seen_lower:
                    continue
                seen_lower.add(key)
                running_entries.append(
                    {
                        "name": app_name,
                        "running": True,
                        "frontmost": front_part.strip().lower() == "true",
                        "favorite": key in favorites_lower,
                    }
                )

        # Sort keeping the frontmost app at the top of the list
        running_entries.sort(key=lambda item: (not item["frontmost"], item["name"].lower()))

        for fav in DEFAULT_FAVORITE_APPS:
            if fav.lower() not in seen_lower:
                running_entries.append(
                    {
                        "name": fav,
                        "running": False,
                        "frontmost": False,
                        "favorite": True,
                    }
                )

        return running_entries

    @staticmethod
    def validate_app_name(app_name: str) -> str | None:
        """Validate an app name against a safe regex and block traversal/options."""
        if not isinstance(app_name, str):
            return None
        cleaned = app_name.strip()
        if not cleaned:
            return None
        if ".." in cleaned or cleaned.startswith("-"):
            return None
        if not _APP_NAME_RE.fullmatch(cleaned):
            return None
        return cleaned

    def activate_app(self, app_name: str) -> dict[str, Any]:
        """Open or bring a macOS app to the foreground with `open -a`."""
        safe_name = self.validate_app_name(app_name)
        if safe_name is None:
            return {
                "ok": False,
                "app": app_name,
                "error": "Invalid or disallowed app name.",
            }

        proc = self._run_cmd(["/usr/bin/open", "-a", safe_name], timeout=5.0)
        if proc.returncode == 0:
            self._invalidate_status_cache()
            return {
                "ok": True,
                "app": safe_name,
                "message": f"App {safe_name} activated.",
            }
        return {
            "ok": False,
            "app": safe_name,
            "error": (proc.stderr or "").strip() or f"Could not open '{safe_name}'.",
        }

    @staticmethod
    def _parse_keys_spec(keys_spec: str) -> tuple[list[str], str] | None:
        """Validate a shortcut spec (e.g. `cmd+opt+f`) against a closed whitelist."""
        if not isinstance(keys_spec, str):
            return None
        raw = keys_spec.strip().lower()
        if not raw:
            return None

        parts = [part.strip() for part in raw.split("+")]
        if any(not part for part in parts) or len(parts) > 5:
            return None

        key_token = parts[-1]
        modifier_tokens = parts[:-1]

        modifiers_set: set[str] = set()
        for mod in modifier_tokens:
            mapped = _MODIFIER_MAP.get(mod)
            if mapped is None:
                return None
            modifiers_set.add(mapped)

        ordered_modifiers = [
            mod for mod in _MODIFIER_CANONICAL_ORDER if mod in modifiers_set
        ]

        if key_token in _SPECIAL_KEY_CODES or _SINGLE_ALNUM_RE.fullmatch(key_token):
            return ordered_modifiers, key_token
        return None

    def execute_keystroke(self, keys_spec: str) -> dict[str, Any]:
        """Run a key combination on macOS via AppleScript `System Events`."""
        parsed = self._parse_keys_spec(keys_spec)
        if parsed is None:
            return {
                "ok": False,
                "needs_accessibility": False,
                "keys": keys_spec,
                "error": f"Invalid or disallowed key spec: '{keys_spec}'.",
            }

        modifiers, key_token = parsed
        if key_token in _SPECIAL_KEY_CODES:
            action_expr = f"key code {_SPECIAL_KEY_CODES[key_token]}"
        else:
            # `key_token` was already validated as a single [a-z0-9] character
            action_expr = f'keystroke "{key_token}"'

        if modifiers:
            using_clause = " using {" + ", ".join(modifiers) + "}"
        else:
            using_clause = ""

        script = f'tell application "System Events" to {action_expr}{using_clause}'
        normalized_spec = keys_spec.strip().lower()
        proc = self._run_cmd(["/usr/bin/osascript", "-e", script], timeout=5.0)

        if proc.returncode == 0:
            return {
                "ok": True,
                "needs_accessibility": False,
                "keys": normalized_spec,
            }

        stderr = (proc.stderr or "").strip()
        if _is_accessibility_error(stderr):
            return {
                "ok": False,
                "needs_accessibility": True,
                "keys": normalized_spec,
                "error": (
                    "Accessibility permission required on macOS. "
                    "Enable it in System Settings → Privacy & Security → Accessibility."
                ),
            }

        return {
            "ok": False,
            "needs_accessibility": False,
            "keys": normalized_spec,
            "error": stderr or "Failed to send the keyboard shortcut.",
        }

    def paste_text(self, text: str) -> dict[str, Any]:
        """Insert text into the focused app via clipboard paste, then restore the previous clipboard.

        The text is passed to `pbcopy` through stdin, never through argv or a shell.
        The text is never included in returned errors.
        """
        if not isinstance(text, str) or not text.strip():
            return {"ok": False, "error": "Nothing to paste."}
        if len(text) > _PASTE_MAX_CHARS:
            return {"ok": False, "error": "Text too long to paste."}

        previous_proc = self._run_cmd([_PBPASTE_BIN], timeout=3.0)
        previous: str | None = (
            (previous_proc.stdout or "") if previous_proc.returncode == 0 else None
        )

        copy_proc = self._run_cmd([_PBCOPY_BIN], timeout=3.0, input_text=text)
        if copy_proc.returncode != 0:
            return {
                "ok": False,
                "error": (copy_proc.stderr or "").strip() or "Could not set the clipboard.",
            }

        try:
            keystroke = self.execute_keystroke("cmd+v")
            time.sleep(_PASTE_SETTLE_SECONDS)
        finally:
            # Always restore the previous clipboard, even when the keystroke failed.
            if previous is not None:
                self._run_cmd([_PBCOPY_BIN], timeout=3.0, input_text=previous)

        if keystroke.get("ok"):
            return {"ok": True, "chars": len(text)}
        return {
            "ok": False,
            "needs_accessibility": bool(keystroke.get("needs_accessibility", False)),
            "error": keystroke.get("error") or "Could not paste the text.",
        }

    def _has_spotify(self) -> bool:
        """Report whether the Spotify AppleScript block should be included."""
        return self._custom_runner is not None or Path("/Applications/Spotify.app").exists()

    def _has_music(self) -> bool:
        """Report whether the Music AppleScript block should be included."""
        return (
            self._custom_runner is not None
            or Path("/System/Applications/Music.app").exists()
            or Path("/Applications/Music.app").exists()
        )

    def _build_mac_status_script(self) -> str:
        """Build the status AppleScript, omitting players that are not installed to avoid compile errors."""
        parts: list[str] = [
            'set activeApp to ""',
            "try",
            '    tell application "System Events"',
            "        set activeApp to name of first application process whose frontmost is true",
            "    end tell",
            "end try",
            'set volLevel to ""',
            'set volMuted to ""',
            "try",
            "    set volInfo to get volume settings",
            "    set volLevel to (output volume of volInfo) as text",
            "    set volMuted to (output muted of volInfo) as text",
            "end try",
            'set npApp to ""',
            'set npState to ""',
            'set npTrack to ""',
            'set npArtist to ""',
        ]

        player_branches: list[str] = []
        if self._has_spotify():
            player_branches.append(
                'if application "Spotify" is running then\n'
                '        tell application "Spotify"\n'
                '            set npApp to "Spotify"\n'
                "            set npState to (player state as text)\n"
                '            if npState is "playing" or npState is "paused" then\n'
                "                set npTrack to (name of current track) as text\n"
                "                set npArtist to (artist of current track) as text\n"
                "            end if\n"
                "        end tell"
            )
        if self._has_music():
            player_branches.append(
                'if application "Music" is running then\n'
                '        tell application "Music"\n'
                '            set npApp to "Music"\n'
                "            set npState to (player state as text)\n"
                '            if npState is "playing" or npState is "paused" then\n'
                "                set npTrack to (name of current track) as text\n"
                "                set npArtist to (artist of current track) as text\n"
                "            end if\n"
                "        end tell"
            )

        if player_branches:
            parts.append("try")
            parts.append("    " + "\n    else ".join(player_branches))
            parts.append("    end if")
            parts.append("end try")

        parts.append(
            'return activeApp & "||" & volLevel & "||" & volMuted & "||" & '
            'npApp & "||" & npState & "||" & npTrack & "||" & npArtist'
        )
        return "\n".join(parts)

    def _run_media_applescript(self, action: str) -> dict[str, Any]:
        """Run a safe media command on Spotify or Music via `osascript`."""
        # `action` comes exclusively from this method's internal whitelist
        branches: list[str] = []
        if self._has_spotify():
            branches.append(
                'if application "Spotify" is running then\n'
                f'    tell application "Spotify" to {action}'
            )
        if self._has_music():
            branches.append(
                'if application "Music" is running then\n'
                f'    tell application "Music" to {action}'
            )

        if not branches:
            return {"ok": True, "output": "no_player"}

        script = "\nelse ".join(branches) + '\nelse\n    return "no_player"\nend if'
        proc = self._run_cmd(["/usr/bin/osascript", "-e", script], timeout=5.0)
        self._invalidate_status_cache()
        if proc.returncode == 0:
            return {"ok": True, "output": (proc.stdout or "").strip()}
        return {
            "ok": False,
            "error": (proc.stderr or "").strip() or "Failed to control media playback.",
        }

    def execute_mac_command(self, command_name: str) -> dict[str, Any]:
        """Run a pre-approved macOS command from the closed whitelist."""
        cmd = str(command_name or "").strip().lower()
        if cmd not in VALID_MAC_COMMANDS:
            return {
                "ok": False,
                "command": command_name,
                "error": f"Command not allowed: '{command_name}'.",
            }

        if cmd == "mission_control":
            proc = self._run_cmd(["/usr/bin/open", "-a", "Mission Control"], timeout=5.0)
            return {
                "ok": proc.returncode == 0,
                "command": cmd,
                "error": (proc.stderr or "").strip() if proc.returncode != 0 else None,
            }

        if cmd == "app_expose":
            script = 'tell application "System Events" to key code 125 using {control down}'
            proc = self._run_cmd(["/usr/bin/osascript", "-e", script], timeout=5.0)
            stderr = (proc.stderr or "").strip()
            if proc.returncode != 0 and _is_accessibility_error(stderr):
                return {
                    "ok": False,
                    "needs_accessibility": True,
                    "command": cmd,
                    "error": (
                        "Accessibility permission required on macOS. "
                        "Enable it in System Settings → Privacy & Security → Accessibility."
                    ),
                }
            return {
                "ok": proc.returncode == 0,
                "command": cmd,
                "error": stderr if proc.returncode != 0 else None,
            }

        if cmd == "space_left":
            res = self.execute_keystroke("ctrl+left")
            res["command"] = cmd
            return res

        if cmd == "space_right":
            res = self.execute_keystroke("ctrl+right")
            res["command"] = cmd
            return res

        if cmd == "toggle_dock":
            res = self.execute_keystroke("opt+cmd+d")
            res["command"] = cmd
            return res

        if cmd == "lock_screen":
            res = self.execute_keystroke("ctrl+cmd+q")
            res["command"] = cmd
            return res

        if cmd == "screenshot_clipboard":
            proc = self._run_cmd(["/usr/sbin/screencapture", "-i", "-c"], timeout=30.0)
            return {
                "ok": proc.returncode == 0,
                "command": cmd,
                "error": (proc.stderr or "").strip() if proc.returncode != 0 else None,
            }

        if cmd in {"screenshot_area_file", "screenshot_file"}:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = Path.home() / "Desktop" / f"Screenshot_{stamp}.png"
            proc = self._run_cmd(
                ["/usr/sbin/screencapture", "-i", str(target)], timeout=30.0
            )
            return {
                "ok": proc.returncode == 0,
                "command": cmd,
                "file": str(target) if proc.returncode == 0 else None,
                "error": (proc.stderr or "").strip() if proc.returncode != 0 else None,
            }

        if cmd == "screenshot_full":
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            target = Path.home() / "Desktop" / f"Screenshot_Full_{stamp}.png"
            proc = self._run_cmd(["/usr/sbin/screencapture", str(target)], timeout=10.0)
            return {
                "ok": proc.returncode == 0,
                "command": cmd,
                "file": str(target) if proc.returncode == 0 else None,
                "error": (proc.stderr or "").strip() if proc.returncode != 0 else None,
            }

        if cmd == "play_pause":
            res = self._run_media_applescript("playpause")
            res["command"] = cmd
            return res

        if cmd == "next_track":
            res = self._run_media_applescript("next track")
            res["command"] = cmd
            return res

        if cmd == "prev_track":
            res = self._run_media_applescript("previous track")
            res["command"] = cmd
            return res

        if cmd == "volume_up":
            script = (
                "set curVol to output volume of (get volume settings)\n"
                "set nextVol to curVol + 6\n"
                "if nextVol > 100 then set nextVol to 100\n"
                "set volume output volume nextVol\n"
                "return nextVol"
            )
            proc = self._run_cmd(["/usr/bin/osascript", "-e", script], timeout=4.0)
            self._invalidate_status_cache()
            return {
                "ok": proc.returncode == 0,
                "command": cmd,
                "volume": int(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip().isdigit() else None,
                "error": (proc.stderr or "").strip() if proc.returncode != 0 else None,
            }

        if cmd == "volume_down":
            script = (
                "set curVol to output volume of (get volume settings)\n"
                "set nextVol to curVol - 6\n"
                "if nextVol < 0 then set nextVol to 0\n"
                "set volume output volume nextVol\n"
                "return nextVol"
            )
            proc = self._run_cmd(["/usr/bin/osascript", "-e", script], timeout=4.0)
            self._invalidate_status_cache()
            return {
                "ok": proc.returncode == 0,
                "command": cmd,
                "volume": int(proc.stdout.strip()) if proc.returncode == 0 and proc.stdout.strip().isdigit() else None,
                "error": (proc.stderr or "").strip() if proc.returncode != 0 else None,
            }

        if cmd == "volume_mute":
            script = (
                "set curMuted to output muted of (get volume settings)\n"
                "set volume output muted (not curMuted)\n"
                "return (not curMuted) as text"
            )
            proc = self._run_cmd(["/usr/bin/osascript", "-e", script], timeout=4.0)
            self._invalidate_status_cache()
            return {
                "ok": proc.returncode == 0,
                "command": cmd,
                "muted": proc.stdout.strip().lower() == "true" if proc.returncode == 0 else None,
                "error": (proc.stderr or "").strip() if proc.returncode != 0 else None,
            }

        if cmd == "pomodoro_start":
            with self._lock:
                self._pomodoro_state = {
                    "active": True,
                    "duration_minutes": 25,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                }
                self._invalidate_status_cache()
                return {
                    "ok": True,
                    "command": cmd,
                    "pomodoro": dict(self._pomodoro_state),
                }

        # pomodoro_stop
        with self._lock:
            self._pomodoro_state = {
                "active": False,
                "duration_minutes": 25,
                "started_at": None,
            }
            self._invalidate_status_cache()
            return {
                "ok": True,
                "command": cmd,
                "pomodoro": dict(self._pomodoro_state),
            }

    def run_shortcut(self, shortcut: dict[str, Any]) -> dict[str, Any]:
        """Dispatch the execution of a shortcut according to its `action_type` and `payload`."""
        if not isinstance(shortcut, dict):
            return {"ok": False, "error": "Invalid shortcut."}

        action_type = str(shortcut.get("action_type") or "").strip()
        payload = shortcut.get("payload") or {}
        if not isinstance(payload, dict):
            payload = {}

        if action_type == "keystroke":
            result = self.execute_keystroke(str(payload.get("keys") or ""))
        elif action_type == "app_activate":
            result = self.activate_app(str(payload.get("app") or ""))
        elif action_type == "mac_command":
            result = self.execute_mac_command(str(payload.get("command") or ""))
        elif action_type == "agent_prompt":
            result = {
                "ok": True,
                "action_type": "agent_prompt",
                "prompt": str(payload.get("prompt") or ""),
            }
        else:
            result = {"ok": False, "error": f"Unsupported action_type: '{action_type}'"}

        if "slug" in shortcut:
            result.setdefault("slug", shortcut["slug"])
        if "title" in shortcut:
            result.setdefault("title", shortcut["title"])
        result.setdefault("action_type", action_type)
        return result

    def _invalidate_status_cache(self) -> None:
        """Invalidate the status cache after actions that change volume/media/focus."""
        with self._lock:
            self._status_cache = None

    def get_mac_status(self) -> dict[str, Any]:
        """Return lightweight Mac telemetry with a 3-second cache."""
        now = time.monotonic()
        with self._lock:
            if self._status_cache is not None:
                cached_at, cached_val = self._status_cache
                if now - cached_at < _STATUS_CACHE_TTL_SECONDS:
                    return dict(cached_val)

        active_app: str | None = None
        volume: int | None = None
        muted: bool | None = None
        now_playing: dict[str, Any] | None = None

        status_script = self._build_mac_status_script()
        osa_proc = self._run_cmd(["/usr/bin/osascript", "-e", status_script], timeout=4.0)
        if osa_proc.returncode == 0 and osa_proc.stdout:
            parts = osa_proc.stdout.strip().split("||")
            if len(parts) >= 7:
                active_app = parts[0].strip() or None
                vol_raw = parts[1].strip()
                if vol_raw.isdigit():
                    volume = int(vol_raw)
                muted_raw = parts[2].strip().lower()
                if muted_raw in {"true", "false"}:
                    muted = muted_raw == "true"
                np_app = parts[3].strip()
                np_state = parts[4].strip().lower()
                np_track = parts[5].strip()
                np_artist = parts[6].strip()
                if np_app and np_state in {"playing", "paused"} and np_track:
                    now_playing = {
                        "app": np_app,
                        "state": np_state,
                        "track": np_track,
                        "artist": np_artist,
                    }

        battery_percent: int | None = None
        charging: bool | None = None
        pm_proc = self._run_cmd(["/usr/bin/pmset", "-g", "batt"], timeout=3.0)
        if pm_proc.returncode == 0 and pm_proc.stdout:
            batt_text = pm_proc.stdout
            pct_match = re.search(r"(\d{1,3})%", batt_text)
            if pct_match:
                battery_percent = max(0, min(100, int(pct_match.group(1))))
            lowered_batt = batt_text.lower()
            if "discharging" in lowered_batt:
                charging = False
            elif "charging" in lowered_batt or "ac power" in lowered_batt or "charged" in lowered_batt:
                charging = True

        with self._lock:
            status: dict[str, Any] = {
                "active_app": active_app,
                "battery_percent": battery_percent,
                "charging": charging,
                "volume": volume,
                "muted": muted,
                "now_playing": now_playing,
                "pomodoro": dict(self._pomodoro_state),
            }
            self._status_cache = (time.monotonic(), status)
            return dict(status)

    def get_weather(
        self,
        latitude: float = -23.5505,
        longitude: float = -46.6333,
        city: str = "São Paulo",
    ) -> dict[str, Any]:
        """Fetch current weather via Open-Meteo with a 15-minute cache and an offline fallback."""
        cache_key = (round(float(latitude), 3), round(float(longitude), 3), str(city))
        now = time.monotonic()

        with self._lock:
            cached = self._weather_cache.get(cache_key)
            if cached is not None:
                cached_at, cached_data = cached
                if now - cached_at < _WEATHER_CACHE_TTL_SECONDS:
                    return dict(cached_data)

        try:
            if self._weather_fetcher is not None:
                payload = self._weather_fetcher(latitude, longitude, city)
            else:
                response = httpx.get(
                    "https://api.open-meteo.com/v1/forecast",
                    params={
                        "latitude": latitude,
                        "longitude": longitude,
                        "current": "temperature_2m,apparent_temperature,weather_code,is_day,wind_speed_10m",
                        "timezone": "auto",
                    },
                    timeout=4.0,
                )
                response.raise_for_status()
                payload = response.json()

            current = payload.get("current") if isinstance(payload, dict) else None
            if not isinstance(current, dict):
                current = payload if isinstance(payload, dict) else {}

            temp_raw = current.get("temperature_2m")
            apparent_raw = current.get("apparent_temperature")
            code_raw = current.get("weather_code")
            wind_raw = current.get("wind_speed_10m")
            is_day_raw = current.get("is_day")

            weather_code = int(code_raw) if code_raw is not None else None
            condition, effect = _interpret_weather_code(weather_code)

            result: dict[str, Any] = {
                "ok": True,
                "offline": False,
                "city": city,
                "temperature_c": float(temp_raw) if temp_raw is not None else None,
                "apparent_c": float(apparent_raw) if apparent_raw is not None else None,
                "wind_kmh": float(wind_raw) if wind_raw is not None else None,
                "is_day": bool(is_day_raw) if is_day_raw is not None else True,
                "weather_code": weather_code,
                "condition": condition,
                "effect": effect,
            }
            with self._lock:
                self._weather_cache[cache_key] = (time.monotonic(), result)
            return dict(result)
        except Exception as exc:
            return {
                "ok": False,
                "offline": True,
                "city": city,
                "temperature_c": None,
                "apparent_c": None,
                "wind_kmh": None,
                "is_day": True,
                "weather_code": None,
                "condition": "Unavailable (offline)",
                "effect": "none",
                "error": str(exc),
            }
