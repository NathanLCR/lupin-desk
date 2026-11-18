"""Tests for the everyday Panel widgets (app.panels.everyday): media, timers, Pomodoro end, calendar."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.actions import ActionRegistry  # noqa: E402
from app.mac_control import VALID_MAC_COMMANDS  # noqa: E402
from app.panels import everyday  # noqa: E402
from app.signals import Importance, Signal  # noqa: E402


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeMac:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.ok = True
        self.pomodoro: dict[str, Any] = {"active": False, "duration_minutes": 25, "started_at": None}
        self.calendar: list[dict[str, Any]] | None = []

    def execute_mac_command(self, command_name: str) -> dict[str, Any]:
        self.calls.append(command_name)
        return {"ok": self.ok, "command": command_name}

    def pomodoro_state(self) -> dict[str, Any]:
        return dict(self.pomodoro)

    def read_today_calendar(self) -> list[dict[str, Any]] | None:
        return self.calendar


class FakeHub:
    def __init__(self) -> None:
        self.published: list[tuple[str, Any]] = []

    async def publish(self, topic: str, payload: Any) -> int:
        self.published.append((topic, payload))
        return 1


class FakeSignals:
    def __init__(self, fail: bool = False) -> None:
        self.emitted: list[Signal] = []
        self.fail = fail

    async def emit(self, signal: Signal) -> None:
        if self.fail:
            raise RuntimeError("boom")
        self.emitted.append(signal)


class Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _local_epoch(hour: int, minute: int) -> float:
    """Epoch seconds for 2026-11-18 at local hh:mm (naive datetime is local time)."""
    return datetime(2026, 11, 18, hour, minute).timestamp()


def _make(
    *,
    clock: Clock | None = None,
    signals_fail: bool = False,
    calendar_reader: Any = None,
    with_actions: bool = True,
) -> dict[str, Any]:
    app = FastAPI()
    mac = FakeMac()
    hub = FakeHub()
    signals = FakeSignals(fail=signals_fail)
    clock = clock or Clock(_local_epoch(9, 0))
    app.state.device_hub = hub
    app.state.signals = signals
    if with_actions:
        app.state.actions = ActionRegistry()
    service = everyday.register(
        app,
        mac,
        calendar_reader=calendar_reader,
        clock=clock,
        interval=0.01,
    )
    return {
        "app": app,
        "mac": mac,
        "hub": hub,
        "signals": signals,
        "clock": clock,
        "service": service,
        "actions": app.state.actions if with_actions else None,
    }


def _run_action(actions: ActionRegistry, action_id: str, args: Any = None) -> dict[str, Any]:
    return asyncio.run(actions.run(action_id, args if args is not None else {}))


# ---------------------------------------------------------------------------
# Media and Pomodoro actions
# ---------------------------------------------------------------------------


def test_media_actions_call_only_whitelisted_commands() -> None:
    env = _make()
    for action_id in [
        "media.play_pause",
        "media.next",
        "media.previous",
        "pomodoro.start",
        "pomodoro.stop",
    ]:
        reply = _run_action(env["actions"], action_id)
        assert reply["ok"] is True, action_id

    assert env["mac"].calls == [
        "play_pause",
        "next_track",
        "prev_track",
        "pomodoro_start",
        "pomodoro_stop",
    ]
    assert set(env["mac"].calls) <= VALID_MAC_COMMANDS


def test_media_failure_is_generic_action_failed() -> None:
    env = _make()
    env["mac"].ok = False
    reply = _run_action(env["actions"], "media.next")
    assert reply == {
        "type": "action_result",
        "id": "media.next",
        "ok": False,
        "error": "action_failed",
    }


def test_media_action_rejects_client_supplied_command_name() -> None:
    env = _make()
    reply = _run_action(env["actions"], "media.next", {"command": "rm -rf /"})
    assert reply["ok"] is True
    assert env["mac"].calls == ["next_track"]


def test_no_actions_registry_is_fine() -> None:
    env = _make(with_actions=False)
    assert env["service"] is env["app"].state.everyday


# ---------------------------------------------------------------------------
# Timers
# ---------------------------------------------------------------------------


def test_timer_start_returns_id_label_seconds_and_publishes() -> None:
    env = _make()
    reply = _run_action(env["actions"], "timers.start", {"seconds": 60, "label": "  Tea  "})
    assert reply["ok"] is True
    result = reply["result"]
    assert result["label"] == "Tea"
    assert result["seconds"] == 60
    assert isinstance(result["id"], str) and result["id"]
    topic, payload = env["hub"].published[-1]
    assert topic == "timers"
    assert payload["timers"] == [
        {"id": result["id"], "label": "Tea", "seconds": 60, "remaining": 60}
    ]


@pytest.mark.parametrize(
    "args",
    [
        {"seconds": True},
        {"seconds": False},
        {"seconds": 1.5},
        {"seconds": 60.0},
        {"seconds": "60"},
        {"seconds": 0},
        {"seconds": -5},
        {"seconds": 86401},
        {},
        {"seconds": 10, "label": 42},
        {"seconds": 10, "label": "x" * 41},
    ],
)
def test_timer_start_rejects_bad_args(args: dict[str, Any]) -> None:
    env = _make()
    reply = _run_action(env["actions"], "timers.start", args)
    assert reply["ok"] is False
    assert reply["error"] == "action_failed"
    assert env["service"].timers.payload() == {"timers": []}


def test_timer_start_accepts_boundaries_and_missing_label() -> None:
    env = _make()
    assert _run_action(env["actions"], "timers.start", {"seconds": 1})["ok"] is True
    assert _run_action(env["actions"], "timers.start", {"seconds": 86400, "label": "x" * 40})["ok"]


def test_timer_limit_is_twenty_active() -> None:
    env = _make()
    for _ in range(20):
        assert _run_action(env["actions"], "timers.start", {"seconds": 30})["ok"] is True
    reply = _run_action(env["actions"], "timers.start", {"seconds": 30})
    assert reply["ok"] is False
    assert len(env["service"].timers.payload()["timers"]) == 20


def test_timer_cancel_and_unknown_id() -> None:
    env = _make()
    started = _run_action(env["actions"], "timers.start", {"seconds": 30})["result"]
    before = len(env["hub"].published)

    reply = _run_action(env["actions"], "timers.cancel", {"id": started["id"]})
    assert reply["result"] == {"id": started["id"], "cancelled": True}
    assert len(env["hub"].published) == before + 1
    assert env["service"].timers.payload() == {"timers": []}

    assert _run_action(env["actions"], "timers.cancel", {"id": started["id"]})["ok"] is False
    assert _run_action(env["actions"], "timers.cancel", {"id": 7})["ok"] is False


def test_remaining_counts_down_with_clock() -> None:
    clock = Clock(1000.0)
    env = _make(clock=clock)
    _run_action(env["actions"], "timers.start", {"seconds": 10})
    clock.now = 1003.0
    assert env["service"].timers.payload()["timers"][0]["remaining"] == 7
    clock.now = 1012.0
    assert env["service"].timers.payload()["timers"][0]["remaining"] == 0


def test_timer_done_emits_signal_once_and_publishes() -> None:
    clock = Clock(1000.0)
    env = _make(clock=clock)
    started = _run_action(env["actions"], "timers.start", {"seconds": 10, "label": "Eggs"})["result"]

    asyncio.run(env["service"].tick())
    assert env["signals"].emitted == []

    clock.now = 1010.0
    asyncio.run(env["service"].tick())
    assert len(env["signals"].emitted) == 1
    signal = env["signals"].emitted[0]
    assert signal.kind == "timer_done"
    assert signal.source == "timers"
    assert signal.importance is Importance.IMPORTANT
    assert signal.data == {"id": started["id"], "label": "Eggs"}
    assert env["hub"].published[-1] == ("timers", {"timers": []})

    asyncio.run(env["service"].tick())
    assert len(env["signals"].emitted) == 1


# ---------------------------------------------------------------------------
# Pomodoro end
# ---------------------------------------------------------------------------


def _pomodoro_started_at(epoch: float, minutes_ago: int) -> str:
    return datetime.fromtimestamp(epoch - minutes_ago * 60, timezone.utc).isoformat()


def test_pomodoro_end_stops_once_and_emits_signal() -> None:
    clock = Clock(_local_epoch(9, 30))
    env = _make(clock=clock)
    env["mac"].pomodoro = {
        "active": True,
        "duration_minutes": 25,
        "started_at": _pomodoro_started_at(clock.now, 24),
    }
    asyncio.run(env["service"].tick())
    assert env["mac"].calls == []

    clock.now += 60
    asyncio.run(env["service"].tick())
    assert env["mac"].calls == ["pomodoro_stop"]
    assert len(env["signals"].emitted) == 1
    signal = env["signals"].emitted[0]
    assert signal.kind == "timer_done"
    assert signal.source == "pomodoro"
    assert signal.data == {"id": "pomodoro", "label": "Pomodoro"}

    env["mac"].pomodoro["active"] = False
    asyncio.run(env["service"].tick())
    assert env["mac"].calls == ["pomodoro_stop"]
    assert len(env["signals"].emitted) == 1


def test_pomodoro_inactive_does_nothing() -> None:
    clock = Clock(_local_epoch(9, 30))
    env = _make(clock=clock)
    env["mac"].pomodoro = {
        "active": False,
        "duration_minutes": 25,
        "started_at": _pomodoro_started_at(clock.now, 120),
    }
    asyncio.run(env["service"].tick())
    assert env["mac"].calls == []
    assert env["signals"].emitted == []


def test_mac_without_pomodoro_state_is_tolerated() -> None:
    class BareMac:
        def execute_mac_command(self, name: str) -> dict[str, Any]:
            return {"ok": True}

        def read_today_calendar(self) -> list[dict[str, Any]]:
            return []

    app = FastAPI()
    app.state.signals = FakeSignals()
    app.state.device_hub = FakeHub()
    service = everyday.register(app, BareMac(), clock=Clock(_local_epoch(9, 0)), interval=0.01)
    asyncio.run(service.tick())
    assert app.state.signals.emitted == []


# ---------------------------------------------------------------------------
# Calendar
# ---------------------------------------------------------------------------


def test_calendar_endpoint_returns_read_only_shape() -> None:
    events = [
        {"start": "09:05", "title": "Standup", "all_day": False, "extra": "dropped"},
        {"start": "00:00", "title": "Holiday", "all_day": True},
    ]
    env = _make(calendar_reader=lambda: events)
    client = TestClient(env["app"])
    response = client.get("/api/panel/calendar")
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "events": [
            {"start": "09:05", "title": "Standup", "all_day": False},
            {"start": "00:00", "title": "Holiday", "all_day": True},
        ],
    }


def test_calendar_endpoint_uses_mac_reader_by_default() -> None:
    env = _make()
    env["mac"].calendar = [{"start": "10:00", "title": "Review", "all_day": False}]
    response = TestClient(env["app"]).get("/api/panel/calendar")
    assert response.json()["events"] == [{"start": "10:00", "title": "Review", "all_day": False}]


def test_calendar_endpoint_none_is_not_ok() -> None:
    env = _make(calendar_reader=lambda: None)
    response = TestClient(env["app"]).get("/api/panel/calendar")
    assert response.json() == {"ok": False, "events": []}


def test_timers_endpoint_matches_publish_payload() -> None:
    env = _make()
    started = _run_action(env["actions"], "timers.start", {"seconds": 45, "label": "Pasta"})["result"]
    response = TestClient(env["app"]).get("/api/panel/timers")
    assert response.json() == {
        "timers": [{"id": started["id"], "label": "Pasta", "seconds": 45, "remaining": 45}]
    }


# ---------------------------------------------------------------------------
# Meetings soon
# ---------------------------------------------------------------------------


def test_meeting_soon_emitted_once_with_calendar_data_class() -> None:
    events = [{"start": "09:05", "title": "Standup", "all_day": False}]
    env = _make(clock=Clock(_local_epoch(9, 0)), calendar_reader=lambda: events)

    asyncio.run(env["service"].tick())
    assert len(env["signals"].emitted) == 1
    signal = env["signals"].emitted[0]
    assert signal.kind == "meeting_soon"
    assert signal.source == "calendar"
    assert signal.importance is Importance.IMPORTANT
    assert signal.data == {"title": "Standup", "start": "09:05"}
    assert signal.data_class == "calendar"

    env["clock"].now += 30
    asyncio.run(env["service"].tick())
    assert len(env["signals"].emitted) == 1


def test_meeting_soon_skips_all_day_past_and_far_events() -> None:
    events = [
        {"start": "09:05", "title": "Holiday", "all_day": True},
        {"start": "08:59", "title": "Earlier", "all_day": False},
        {"start": "10:00", "title": "Later", "all_day": False},
    ]
    env = _make(clock=Clock(_local_epoch(9, 0)), calendar_reader=lambda: events)
    asyncio.run(env["service"].tick())
    assert env["signals"].emitted == []


def test_meeting_announced_key_clears_on_new_day() -> None:
    events = [{"start": "09:05", "title": "Standup", "all_day": False}]
    clock = Clock(_local_epoch(9, 0))
    env = _make(clock=clock, calendar_reader=lambda: events)
    asyncio.run(env["service"].tick())
    assert len(env["signals"].emitted) == 1

    clock.now = datetime(2026, 11, 19, 9, 0).timestamp()
    asyncio.run(env["service"].tick())
    assert len(env["signals"].emitted) == 2


def test_calendar_read_is_throttled_to_once_per_minute() -> None:
    reads: list[int] = []

    def reader() -> list[dict[str, Any]]:
        reads.append(1)
        return []

    clock = Clock(_local_epoch(9, 0))
    env = _make(clock=clock, calendar_reader=reader)
    asyncio.run(env["service"].tick())
    clock.now += 30
    asyncio.run(env["service"].tick())
    assert len(reads) == 1
    clock.now += 31
    asyncio.run(env["service"].tick())
    assert len(reads) == 2


def test_failing_signals_emit_does_not_break_tick() -> None:
    clock = Clock(_local_epoch(9, 0))
    events = [{"start": "09:05", "title": "Standup", "all_day": False}]
    env = _make(clock=clock, signals_fail=True, calendar_reader=lambda: events)
    _run_action(env["actions"], "timers.start", {"seconds": 1})
    clock.now += 5
    asyncio.run(env["service"].tick())  # must not raise
    assert env["service"].timers.payload() == {"timers": []}


def test_failing_calendar_reader_does_not_break_tick() -> None:
    def broken() -> list[dict[str, Any]]:
        raise OSError("calendar unavailable")

    env = _make(calendar_reader=broken)
    asyncio.run(env["service"].tick())  # must not raise
    assert env["signals"].emitted == []


# ---------------------------------------------------------------------------
# Background loop
# ---------------------------------------------------------------------------


def test_start_and_stop_run_the_loop() -> None:
    async def scenario() -> None:
        clock = Clock(1000.0)
        env = _make(clock=clock)
        service = env["service"]
        await env["actions"].run("timers.start", {"seconds": 1})
        clock.now = 1005.0
        service.start()
        service.start()  # idempotent
        for _ in range(100):
            if env["signals"].emitted:
                break
            await asyncio.sleep(0.01)
        await service.stop()
        await service.stop()  # safe to call again
        assert len(env["signals"].emitted) == 1

    asyncio.run(scenario())
