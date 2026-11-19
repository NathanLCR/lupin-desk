"""Tests for Mac monitoring (P08): sampler, heavy-load detector and the subscription-gated collector."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fastapi import FastAPI

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.monitoring import (  # noqa: E402
    HEAVY_LOAD_KIND,
    HeavyLoadDetector,
    Monitoring,
    register,
)
from app.monitoring.sampler import Sampler  # noqa: E402


class FakePsutil:
    def __init__(self) -> None:
        self.cpu = 12.0
        self.sent = 0
        self.recv = 0
        self.process_calls = 0
        self.partitions = [
            SimpleNamespace(device="/dev/disk1", mountpoint="/"),
            SimpleNamespace(device="/dev/disk1", mountpoint="/System/Volumes/Data"),
            SimpleNamespace(device="/dev/disk2", mountpoint="/Volumes/Backup"),
            SimpleNamespace(device="/dev/disk3", mountpoint="/private/var/vm"),
        ]

    def cpu_percent(self, interval=None) -> float:
        return self.cpu

    def cpu_count(self) -> int:
        return 8

    def virtual_memory(self):
        return SimpleNamespace(percent=50.0, used=8 * 1024**3, total=16 * 1024**3)

    def disk_partitions(self, all=False):
        return self.partitions

    def disk_usage(self, mount):
        return SimpleNamespace(percent=40.0, used=100, total=250)

    def net_io_counters(self):
        return SimpleNamespace(bytes_sent=self.sent, bytes_recv=self.recv)

    def process_iter(self, attrs=None):
        self.process_calls += 1
        names = [("a", 5.0), ("b", 50.0), ("c", 20.0), ("d", 1.0), ("e", 2.0), ("f", 30.0), (None, 0.0)]
        for index, (name, cpu) in enumerate(names):
            yield SimpleNamespace(info={"pid": index, "name": name, "cpu_percent": cpu, "memory_percent": 1.0})


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def make_sampler(ps: FakePsutil, clock: Clock, ping_values: list[Any] | None = None) -> Sampler:
    values = ping_values if ping_values is not None else [12.5]
    return Sampler(ps, ping=lambda: values[0], clock=clock)


def test_sample_shape_and_no_gpu() -> None:
    ps, clock = FakePsutil(), Clock()
    sample = make_sampler(ps, clock).sample()
    assert sample["cpu"] == {"percent": 12.0, "cores": 8}
    assert sample["ram"]["percent"] == 50.0
    assert "gpu" not in sample
    assert sample["ping"]["ms"] == 12.5
    assert [d["mount"] for d in sample["disks"]] == ["/", "/Volumes/Backup"]  # one per device, no system volumes
    assert [p["name"] for p in sample["processes"]] == ["b", "f", "c", "a", "e"]


def test_network_rate_is_bytes_per_second() -> None:
    ps, clock = FakePsutil(), Clock()
    sampler = make_sampler(ps, clock)
    assert sampler.sample()["net"] == {"up_bps": 0, "down_bps": 0}
    clock.now = 2.0
    ps.sent, ps.recv = 2000, 10000
    assert sampler.sample()["net"] == {"up_bps": 1000, "down_bps": 5000}


def test_slow_reads_are_cached_between_samples() -> None:
    ps, clock = FakePsutil(), Clock()
    sampler = make_sampler(ps, clock)
    sampler.sample()
    clock.now = 1.0
    sampler.sample()
    assert ps.process_calls == 1
    clock.now = 4.0
    sampler.sample()
    assert ps.process_calls == 2


def test_failed_ping_is_none() -> None:
    ps, clock = FakePsutil(), Clock()
    sampler = Sampler(ps, ping=lambda: (_ for _ in ()).throw(OSError("down")), clock=clock)
    assert sampler.sample()["ping"]["ms"] is None


def test_detector_fires_once_after_the_window_and_rearms() -> None:
    detector = HeavyLoadDetector(threshold=85.0, window=120.0, smoothing=1)
    fired = [detector.feed(float(t), 95.0) for t in range(0, 300)]
    assert fired.count(True) == 1
    assert fired.index(True) == 120
    assert detector.feed(300.0, 10.0) is False
    assert [detector.feed(301.0 + t, 95.0) for t in range(0, 121)].count(True) == 1


def test_detector_ignores_a_short_spike() -> None:
    detector = HeavyLoadDetector(threshold=85.0, window=120.0, smoothing=1)
    results = [detector.feed(float(t), 99.0 if t < 60 else 20.0) for t in range(0, 300)]
    assert not any(results)


class FakeHub:
    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []
        self.published: list[tuple[str, Any]] = []

    async def publish(self, topic: str, payload: Any) -> int:
        self.published.append((topic, payload))
        return 1


class FakeBus:
    def __init__(self) -> None:
        self.signals: list[Any] = []

    async def emit(self, signal: Any) -> None:
        self.signals.append(signal)


def make_app() -> tuple[FastAPI, FakeHub, FakeBus]:
    app = FastAPI()
    hub, bus = FakeHub(), FakeBus()
    app.state.device_hub = hub
    app.state.signals = bus
    return app, hub, bus


async def test_tick_does_nothing_without_a_subscriber() -> None:
    app, hub, _bus = make_app()
    ps = FakePsutil()
    monitoring = register(app, make_sampler(ps, Clock()))
    hub.entries.append({"topics": ["layout"]})
    assert await monitoring.tick() is None
    assert hub.published == []
    assert app.state.monitoring is monitoring


async def test_tick_publishes_to_subscribers() -> None:
    app, hub, _bus = make_app()
    monitoring = Monitoring(app, make_sampler(FakePsutil(), Clock()))
    hub.entries.append({"topics": ["layout", "monitor"]})
    snapshot = await monitoring.tick()
    assert snapshot is not None
    assert hub.published == [("monitor", snapshot)]


async def test_sustained_load_emits_one_signal() -> None:
    app, hub, bus = make_app()
    ps, clock = FakePsutil(), Clock()
    ps.cpu = 97.0
    monitoring = Monitoring(app, make_sampler(ps, clock), clock=clock)
    hub.entries.append({"topics": ["monitor"]})
    for second in range(0, 200):
        clock.now = float(second)
        await monitoring.tick()
    assert [s.kind for s in bus.signals] == [HEAVY_LOAD_KIND]
    assert bus.signals[0].data["cpu_percent"] == 97.0


async def test_pause_resets_the_detector() -> None:
    app, hub, bus = make_app()
    ps, clock = FakePsutil(), Clock()
    ps.cpu = 97.0
    monitoring = Monitoring(app, make_sampler(ps, clock), clock=clock)
    entry = {"topics": ["monitor"]}
    hub.entries.append(entry)
    for second in range(0, 100):
        clock.now = float(second)
        await monitoring.tick()
    hub.entries.clear()
    await monitoring.tick()
    hub.entries.append(entry)
    for second in range(100, 200):
        clock.now = float(second)
        await monitoring.tick()
    assert bus.signals == []


async def test_start_and_stop_run_the_loop_cleanly() -> None:
    app, hub, _bus = make_app()
    monitoring = Monitoring(app, make_sampler(FakePsutil(), Clock()), interval=0.01)
    hub.entries.append({"topics": ["monitor"]})
    monitoring.start()
    await asyncio.sleep(0.1)
    await monitoring.stop()
    assert len(hub.published) >= 2
    count = len(hub.published)
    await asyncio.sleep(0.05)
    assert len(hub.published) == count
