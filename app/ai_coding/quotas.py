"""Quotas and token use, from real local data only. Nothing here invents a limit.

Claude Code exposes no limit locally, so it only gets tokens per day. Codex writes its rate limit
(percent used, window length, reset time) into its session files; when that is present we show it
with a burn-rate forecast, otherwise we also show tokens per day.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.ai_coding.sessions import SessionInfo

DAYS = 7


def daily_tokens(sessions: list[SessionInfo], tool: str, now: float) -> list[dict[str, Any]]:
    """Tokens per UTC day for the last DAYS days (oldest first), zero-filled."""
    totals: dict[str, int] = {}
    for session in sessions:
        if session.tool == tool:
            for day, count in session.by_day.items():
                totals[day] = totals.get(day, 0) + count
    today = datetime.fromtimestamp(now, tz=timezone.utc).date()
    out = []
    for offset in range(DAYS - 1, -1, -1):
        day = (today - timedelta(days=offset)).isoformat()
        out.append({"day": day, "tokens": totals.get(day, 0)})
    return out


def _percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return max(0.0, min(100.0, float(value)))


def forecast(used_percent: float, window_minutes: float, resets_at: float, now: float) -> dict[str, Any] | None:
    """Burn rate and projection for one rate-limit window; None when the numbers cannot say."""
    remaining = (resets_at - now) / 60.0
    if window_minutes <= 0 or remaining <= 0 or remaining > window_minutes:
        return None
    elapsed = window_minutes - remaining
    if elapsed <= 0 or used_percent <= 0:
        return {"percent_per_hour": 0.0, "projected_percent_at_reset": used_percent, "exhausted_in_minutes": None}
    rate = used_percent / elapsed  # percent per minute
    projected = used_percent + rate * remaining
    exhausted = None
    if projected > 100.0 and used_percent < 100.0:
        exhausted = round((100.0 - used_percent) / rate)
    return {
        "percent_per_hour": round(rate * 60.0, 2),
        "projected_percent_at_reset": round(min(projected, 999.0), 1),
        "exhausted_in_minutes": exhausted,
    }


def _window(raw: Any, now: float) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    used = _percent(raw.get("used_percent"))
    minutes = raw.get("window_minutes")
    resets = raw.get("resets_at")
    if used is None or not isinstance(minutes, (int, float)) or not isinstance(resets, (int, float)):
        return None
    if resets <= now:
        return None  # a window that already reset is stale data, not a current limit
    return {
        "used_percent": used,
        "window_minutes": minutes,
        "resets_at": resets,
        "forecast": forecast(used, float(minutes), float(resets), now),
    }


def build_quotas(sessions: list[SessionInfo], now: float) -> dict[str, Any]:
    latest_codex = None
    for session in sorted(sessions, key=lambda s: s.last, reverse=True):
        if session.tool == "codex" and session.rate_limits:
            latest_codex = session.rate_limits
            break
    windows = []
    if latest_codex:
        for name in ("primary", "secondary"):
            window = _window(latest_codex.get(name), now)
            if window is not None:
                window["name"] = name
                windows.append(window)
    return {
        "claude": {"limits": [], "daily_tokens": daily_tokens(sessions, "claude", now)},
        "codex": {"limits": windows, "daily_tokens": daily_tokens(sessions, "codex", now)},
    }
