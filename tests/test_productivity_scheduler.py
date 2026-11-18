"""Unit tests for the habit reminder scheduler: due habits become habit_due Signals, once per day."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.productivity.scheduler import HabitScheduler  # noqa: E402
from app.productivity.store import ProductivityStore  # noqa: E402
from app.signals import Importance, Signal  # noqa: E402


class Clock:
    """Mutable naive local clock."""

    def __init__(self, moment: datetime) -> None:
        self.now = moment

    def __call__(self) -> datetime:
        return self.now


class FakeBus:
    """Records every emitted signal; can raise for chosen habit names."""

    def __init__(self, raise_for: set[str] | None = None, result: Any = None) -> None:
        self.emitted: list[Signal] = []
        self.raise_for = raise_for or set()
        self.result = result

    async def emit(self, signal: Signal) -> Any:
        if signal.data.get("name") in self.raise_for:
            raise RuntimeError("boom")
        self.emitted.append(signal)
        return self.result


def _store(tmp_path: Path, clock: Clock) -> ProductivityStore:
    return ProductivityStore(tmp_path / "productivity.db", clock=clock)


def _scheduler(store: ProductivityStore, bus: Any, clock: Clock, **kwargs: Any) -> HabitScheduler:
    return HabitScheduler(
        store,
        lambda: bus,
        clock=clock,
        line=lambda name: f"due {name}",
        **kwargs,
    )


def test_nothing_due_emits_nothing(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 8, 0))
    store = _store(tmp_path, clock)
    store.add_habit("Water", time="09:00")
    bus = FakeBus()

    assert asyncio.run(_scheduler(store, bus, clock).tick()) == 0
    assert bus.emitted == []
    store.close()


def test_due_habit_emits_one_signal(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    habit = store.add_habit("Water", time="09:00")
    bus = FakeBus()

    assert asyncio.run(_scheduler(store, bus, clock).tick()) == 1
    assert len(bus.emitted) == 1
    signal = bus.emitted[0]
    assert signal.kind == "habit_due"
    assert signal.source == "habits"
    assert signal.importance is Importance.IMPORTANT
    assert signal.summary == "due Water"
    assert signal.data == {"id": habit["id"], "name": "Water", "streak": 0}
    store.close()


def test_second_tick_same_day_does_not_repeat(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    store.add_habit("Water", time="09:00")
    bus = FakeBus()
    scheduler = _scheduler(store, bus, clock)

    async def run() -> tuple[int, int]:
        first = await scheduler.tick()
        clock.now = datetime(2026, 11, 18, 15, 30)
        second = await scheduler.tick()
        return first, second

    assert asyncio.run(run()) == (1, 0)
    assert len(bus.emitted) == 1
    store.close()


def test_next_day_emits_again(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    store.add_habit("Water", time="09:00")
    bus = FakeBus()
    scheduler = _scheduler(store, bus, clock)

    async def run() -> tuple[int, int]:
        first = await scheduler.tick()
        clock.now = datetime(2026, 11, 19, 9, 0)
        second = await scheduler.tick()
        return first, second

    assert asyncio.run(run()) == (1, 1)
    assert [s.data["name"] for s in bus.emitted] == ["Water", "Water"]
    store.close()


def test_checked_in_habit_is_not_emitted(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    habit = store.add_habit("Water", time="09:00")
    store.check_in(habit["id"], day="2026-11-18")
    bus = FakeBus()

    assert asyncio.run(_scheduler(store, bus, clock).tick()) == 0
    assert bus.emitted == []
    store.close()


def test_no_bus_emits_nothing_and_habit_stays_due(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    habit = store.add_habit("Water", time="09:00")
    scheduler = HabitScheduler(store, lambda: None, clock=clock, line=lambda n: n)

    assert asyncio.run(scheduler.tick()) == 0
    assert [h["id"] for h in store.due_habits(clock())] == [habit["id"]]
    store.close()


def test_rate_limited_result_still_marks_habit(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    store.add_habit("Water", time="09:00")
    bus = FakeBus(result=SimpleNamespace(spoke=False, reason="rate_limited"))

    assert asyncio.run(_scheduler(store, bus, clock).tick()) == 1
    assert store.due_habits(clock()) == []
    store.close()


def test_emit_failure_leaves_habit_due_and_others_processed(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    store.add_habit("Water", time="09:00")
    store.add_habit("Stretch", time="09:00")
    bus = FakeBus(raise_for={"Water"})
    scheduler = _scheduler(store, bus, clock)

    async def run() -> tuple[int, int]:
        first = await scheduler.tick()
        bus.raise_for = set()
        second = await scheduler.tick()
        return first, second

    with caplog.at_level(logging.WARNING, logger="app.productivity.scheduler"):
        assert asyncio.run(run()) == (1, 1)

    assert [s.data["name"] for s in bus.emitted] == ["Stretch", "Water"]
    assert "Water" not in caplog.text
    assert "RuntimeError" in caplog.text
    store.close()


def test_start_and_stop_run_the_loop(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    store.add_habit("Water", time="09:00")
    bus = FakeBus()
    sleeps: list[float] = []

    async def run() -> None:
        gate = asyncio.Event()

        async def fake_sleep(seconds: float) -> None:
            sleeps.append(seconds)
            await gate.wait()
            gate.clear()

        scheduler = _scheduler(store, bus, clock, interval=15.0, sleep=fake_sleep)
        scheduler.start()
        scheduler.start()  # idempotent: still one loop

        for _ in range(1000):
            if sleeps:
                break
            await asyncio.sleep(0)
        assert sleeps == [15.0]
        assert len(bus.emitted) == 1

        gate.set()  # release the sleep: the second tick runs, same day, so no re-emit
        for _ in range(1000):
            if len(sleeps) >= 2:
                break
            await asyncio.sleep(0)
        assert len(sleeps) >= 2
        assert len(bus.emitted) == 1

        task = scheduler._task
        assert task is not None
        await scheduler.stop()
        assert task.cancelled() or task.done()
        assert scheduler._task is None
        await scheduler.stop()  # idempotent

    asyncio.run(run())
    store.close()


def test_stop_without_start_is_safe(tmp_path: Path) -> None:
    clock = Clock(datetime(2026, 11, 18, 9, 0))
    store = _store(tmp_path, clock)
    scheduler = _scheduler(store, FakeBus(), clock)

    asyncio.run(scheduler.stop())
    store.close()
