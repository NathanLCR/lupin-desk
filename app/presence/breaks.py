"""Break reminder logic (Lupin 04): pure state, no I/O, injectable clock.

Continuous work is keyboard/mouse input within the last 5 minutes (HIDIdleTime). A break is
5+ minutes idle and resets the work clock. A reminder is due after `interval_minutes` of
continuous work, unless snoozed (a touch snoozes 10 minutes), muted by a Pomodoro, or another
reminder went out less than 20 minutes ago. After a reminder the work clock restarts, so the
next one is a full interval later.
"""

from __future__ import annotations

from dataclasses import dataclass

ACTIVE_WINDOW_SECONDS = 5 * 60  # input within this window counts as working
BREAK_IDLE_SECONDS = 5 * 60  # idle at least this long counts as a break
DEFAULT_INTERVAL_MINUTES = 50
MIN_INTERVAL_MINUTES = 20  # never below the reminder rate limit
MAX_INTERVAL_MINUTES = 240
SNOOZE_SECONDS = 10 * 60
MIN_GAP_SECONDS = 20 * 60  # at most one reminder per 20 minutes


def clamp_interval(minutes: float) -> int:
    return int(max(MIN_INTERVAL_MINUTES, min(MAX_INTERVAL_MINUTES, round(minutes))))


@dataclass
class BreakTracker:
    interval_minutes: int = DEFAULT_INTERVAL_MINUTES
    enabled: bool = True
    _work_started: float | None = None
    _snooze_until: float = 0.0
    _last_reminder: float | None = None

    def set_interval(self, minutes: float) -> int:
        self.interval_minutes = clamp_interval(minutes)
        return self.interval_minutes

    def snooze(self, now: float) -> None:
        """A touch (or "later" by voice) postpones the next reminder by 10 minutes."""
        self._snooze_until = max(self._snooze_until, now + SNOOZE_SECONDS)

    def work_minutes(self, now: float) -> int:
        if self._work_started is None:
            return 0
        return int((now - self._work_started) // 60)

    def update(self, now: float, idle_seconds: float | None, pomodoro_active: bool = False) -> bool:
        """Feed one sample; True when a reminder is due right now.

        `idle_seconds` is None when the idle time could not be read: nothing changes.
        """
        if idle_seconds is None:
            return False
        if idle_seconds >= BREAK_IDLE_SECONDS:
            self._work_started = None
            return False
        if idle_seconds >= ACTIVE_WINDOW_SECONDS:
            return False
        if pomodoro_active:
            # The Pomodoro has its own breaks: restart the clock and stay silent.
            self._work_started = now
            return False
        if self._work_started is None:
            self._work_started = now - idle_seconds
        if not self.enabled:
            return False
        if now - self._work_started < self.interval_minutes * 60:
            return False
        if now < self._snooze_until:
            return False
        if self._last_reminder is not None and now - self._last_reminder < MIN_GAP_SECONDS:
            return False
        return True

    def mark_reminded(self, now: float) -> None:
        self._last_reminder = now
        self._work_started = now
