"""Local Claude Code and Codex sessions, read from their transcript files (read-only).

Only summary numbers leave this module (project name, model, status, duration, token counts,
tokens per day). Prompt text, tool arguments and file contents are never kept or returned.
Every root is injectable; tests point it at a tmp_path.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ACTIVE_SECONDS = 120.0
IDLE_SECONDS = 3600.0
MAX_SESSIONS = 20
MAX_AGE_SECONDS = 7 * 24 * 3600.0


@dataclass
class SessionInfo:
    tool: str  # "claude" | "codex"
    id: str
    cwd: str = ""
    model: str = ""
    started: float = 0.0
    last: float = 0.0
    tokens: int = 0
    cached_tokens: int = 0
    by_day: dict[str, int] = field(default_factory=dict)
    rate_limits: dict[str, Any] | None = None

    @property
    def project(self) -> str:
        return os.path.basename(self.cwd.rstrip("/")) or "unknown"

    def status(self, now: float) -> str:
        age = now - self.last
        if age <= ACTIVE_SECONDS:
            return "active"
        return "idle" if age <= IDLE_SECONDS else "ended"

    def to_public(self, now: float) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "id": self.id,
            "project": self.project,
            "model": self.model,
            "status": self.status(now),
            "duration_seconds": max(0, int(self.last - self.started)) if self.started else 0,
            "tokens": self.tokens,
            "cached_tokens": self.cached_tokens,
            "last_activity": self.last,
        }


def _ts(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _day(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d")


def _int(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _records(path: Path):
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict):
                    yield record
    except OSError:
        return


def _parse_claude(path: Path) -> SessionInfo:
    info = SessionInfo(tool="claude", id=path.stem)
    usage_by_message: dict[str, tuple[int, int, str]] = {}
    anonymous = 0
    for record in _records(path):
        ts = _ts(record.get("timestamp"))
        if ts is not None:
            if not info.started:
                info.started = ts
            info.last = max(info.last, ts)
        if not info.cwd and isinstance(record.get("cwd"), str):
            info.cwd = record["cwd"]
        if record.get("type") != "assistant" or not isinstance(record.get("message"), dict):
            continue
        message = record["message"]
        model = message.get("model")
        if isinstance(model, str) and model and not model.startswith("<"):
            info.model = model
        usage = message.get("usage")
        if not isinstance(usage, dict):
            continue
        fresh = _int(usage.get("input_tokens")) + _int(usage.get("output_tokens"))
        cached = _int(usage.get("cache_creation_input_tokens")) + _int(
            usage.get("cache_read_input_tokens")
        )
        key = message.get("id")
        if not isinstance(key, str):
            anonymous += 1
            key = f"anon{anonymous}"
        # A streamed answer writes several lines with the same message id: keep the last.
        usage_by_message[key] = (fresh, cached, _day(ts) if ts is not None else "")
    for fresh, cached, day in usage_by_message.values():
        info.tokens += fresh
        info.cached_tokens += cached
        if day:
            info.by_day[day] = info.by_day.get(day, 0) + fresh
    return info


def _parse_codex(path: Path) -> SessionInfo:
    info = SessionInfo(tool="codex", id=path.stem)
    for record in _records(path):
        ts = _ts(record.get("timestamp"))
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        if ts is not None:
            info.started = info.started or ts
            info.last = max(info.last, ts)
        kind = record.get("type")
        if kind == "session_meta":
            if isinstance(payload.get("cwd"), str) and not info.cwd:
                info.cwd = payload["cwd"]
            if isinstance(payload.get("id"), str):
                info.id = payload["id"]
            meta_ts = _ts(payload.get("timestamp"))
            if meta_ts is not None:
                info.started = meta_ts
        elif kind == "turn_context" and isinstance(payload.get("model"), str):
            info.model = payload["model"]
        elif kind == "event_msg" and payload.get("type") == "token_count":
            usage = payload.get("info")
            usage = usage if isinstance(usage, dict) else {}
            total = usage.get("total_token_usage")
            if isinstance(total, dict):
                info.tokens = _int(total.get("total_tokens")) or (
                    _int(total.get("input_tokens")) + _int(total.get("output_tokens"))
                )
                info.cached_tokens = _int(total.get("cached_input_tokens"))
            last = usage.get("last_token_usage")
            if isinstance(last, dict) and ts is not None:
                day = _day(ts)
                info.by_day[day] = info.by_day.get(day, 0) + _int(last.get("total_tokens"))
            if isinstance(payload.get("rate_limits"), dict):
                info.rate_limits = payload["rate_limits"]
    return info


class SessionReader:
    """Reads recent sessions with a small cache keyed by file mtime and size."""

    def __init__(self, claude_root: Path | None, codex_root: Path | None) -> None:
        self._claude_root = claude_root
        self._codex_root = codex_root
        self._cache: dict[str, tuple[tuple[int, int], SessionInfo]] = {}

    def _files(self, root: Path | None, matcher, depth: int | None = None) -> list[tuple[float, Path, int]]:
        found: list[tuple[float, Path, int]] = []
        if root is None or not root.is_dir():
            return found
        for current, _dirs, names in os.walk(root):
            for name in names:
                if not matcher(name):
                    continue
                path = Path(current) / name
                if depth is not None and len(path.relative_to(root).parts) != depth:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                found.append((stat.st_mtime, path, stat.st_size))
        found.sort(key=lambda item: item[0], reverse=True)
        return found

    def _load(self, tool: str, mtime: float, path: Path, size: int, parse) -> SessionInfo:
        key = str(path)
        signature = (int(mtime * 1000), size)
        cached = self._cache.get(key)
        if cached is not None and cached[0] == signature:
            return cached[1]
        info = parse(path)
        if not info.last:
            info.last = mtime
        self._cache[key] = (signature, info)
        return info

    def read(self, now: float) -> list[SessionInfo]:
        """Recent sessions (last 7 days), newest first, at most MAX_SESSIONS per tool."""
        out: list[SessionInfo] = []
        sources = (
            ("claude", self._claude_root, lambda n: n.endswith(".jsonl"), _parse_claude, 2),
            ("codex", self._codex_root, lambda n: n.startswith("rollout-") and n.endswith(".jsonl"), _parse_codex, None),
        )
        for tool, root, matcher, parse, depth in sources:
            kept = 0
            for mtime, path, size in self._files(root, matcher, depth):
                if now - mtime > MAX_AGE_SECONDS or kept >= MAX_SESSIONS:
                    break
                out.append(self._load(tool, mtime, path, size, parse))
                kept += 1
        out.sort(key=lambda s: s.last, reverse=True)
        return out
