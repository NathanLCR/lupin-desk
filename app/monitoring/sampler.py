"""Reads Mac stats with psutil: CPU, RAM, disks, network, ping and the top processes.

One `Sampler.sample()` call returns a JSON-ready dict. It is blocking (a few psutil calls and,
now and then, a short TCP connect), so the caller runs it in a thread.

There is no GPU entry on purpose: macOS only exposes it through sudo tools (powermetrics), and
the decision is to hide it rather than add a sudo helper.
"""

from __future__ import annotations

import logging
import socket
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

# Ping is a TCP connect to a public DNS resolver: no subprocess, no ICMP privileges needed.
DEFAULT_PING_TARGET = ("1.1.1.1", 443)
PING_TIMEOUT_SECONDS = 1.5
PING_EVERY_SECONDS = 5.0
PROCESSES_EVERY_SECONDS = 3.0
DISKS_EVERY_SECONDS = 15.0
TOP_PROCESSES = 5
MAX_DISKS = 4
MAX_NAME_LENGTH = 40


def tcp_ping(target: tuple[str, int] = DEFAULT_PING_TARGET, timeout: float = PING_TIMEOUT_SECONDS) -> float | None:
    """Milliseconds to open a TCP connection, or None when it fails."""
    started = time.perf_counter()
    try:
        with socket.create_connection(target, timeout=timeout):
            pass
    except OSError:
        return None
    return round((time.perf_counter() - started) * 1000, 1)


class Sampler:
    def __init__(
        self,
        psutil_module: Any = None,
        *,
        ping: Callable[[], float | None] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if psutil_module is None:
            import psutil as psutil_module  # imported late so the Brain still starts without it
        self._ps = psutil_module
        self._ping = ping if ping is not None else tcp_ping
        self._clock = clock
        self._net_last: tuple[float, int, int] | None = None
        self._processes: list[dict[str, Any]] = []
        self._processes_at: float | None = None
        self._disks: list[dict[str, Any]] = []
        self._disks_at: float | None = None
        self._ping_ms: float | None = None
        self._ping_at: float | None = None

    def reset(self) -> None:
        """Forget rates and caches (used after a pause, so the first rate is not a long average)."""
        self._net_last = None
        self._processes_at = None
        self._disks_at = None
        self._ping_at = None

    def prime(self) -> None:
        """Start psutil's CPU counters (system and per process), whose first reading is a stale 0.0."""
        try:
            self._ps.cpu_percent(None)
            for proc in self._ps.process_iter(["cpu_percent"]):
                pass
        except Exception as exc:
            logger.warning("CPU priming failed (%s).", type(exc).__name__)

    def sample(self) -> dict[str, Any]:
        ps = self._ps
        now = self._clock()
        memory = ps.virtual_memory()
        return {
            "ts": time.time(),
            "cpu": {"percent": float(ps.cpu_percent(interval=None)), "cores": int(ps.cpu_count() or 0)},
            "ram": {"percent": float(memory.percent), "used": int(memory.used), "total": int(memory.total)},
            "disks": self._read_disks(now),
            "net": self._read_net(now),
            "ping": {"ms": self._read_ping(now), "target": DEFAULT_PING_TARGET[0]},
            "processes": self._read_processes(now),
        }

    def _due(self, last: float | None, now: float, every: float) -> bool:
        return last is None or now - last >= every

    def _read_disks(self, now: float) -> list[dict[str, Any]]:
        if not self._due(self._disks_at, now, DISKS_EVERY_SECONDS):
            return self._disks
        self._disks_at = now
        disks: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            partitions = self._ps.disk_partitions(all=False)
        except Exception as exc:
            logger.warning("Disk list failed (%s).", type(exc).__name__)
            return self._disks
        for part in partitions:
            mount = part.mountpoint
            if mount != "/" and not mount.startswith("/Volumes/"):
                continue
            if part.device in seen:
                continue
            seen.add(part.device)
            try:
                usage = self._ps.disk_usage(mount)
            except Exception:
                continue
            disks.append(
                {
                    "mount": mount,
                    "percent": float(usage.percent),
                    "used": int(usage.used),
                    "total": int(usage.total),
                }
            )
            if len(disks) >= MAX_DISKS:
                break
        self._disks = disks
        return disks

    def _read_net(self, now: float) -> dict[str, int]:
        counters = self._ps.net_io_counters()
        sent, recv = int(counters.bytes_sent), int(counters.bytes_recv)
        up = down = 0
        if self._net_last is not None:
            then, last_sent, last_recv = self._net_last
            elapsed = now - then
            if elapsed > 0:
                up = max(0, int((sent - last_sent) / elapsed))
                down = max(0, int((recv - last_recv) / elapsed))
        self._net_last = (now, sent, recv)
        return {"up_bps": up, "down_bps": down}

    def _read_ping(self, now: float) -> float | None:
        if self._due(self._ping_at, now, PING_EVERY_SECONDS):
            self._ping_at = now
            try:
                self._ping_ms = self._ping()
            except Exception:
                self._ping_ms = None
        return self._ping_ms

    def _read_processes(self, now: float) -> list[dict[str, Any]]:
        if not self._due(self._processes_at, now, PROCESSES_EVERY_SECONDS):
            return self._processes
        self._processes_at = now
        rows: list[dict[str, Any]] = []
        try:
            for proc in self._ps.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                info = proc.info
                rows.append(
                    {
                        "pid": int(info["pid"]),
                        "name": str(info.get("name") or "?")[:MAX_NAME_LENGTH],
                        "cpu": round(float(info.get("cpu_percent") or 0.0), 1),
                        "mem": round(float(info.get("memory_percent") or 0.0), 1),
                    }
                )
        except Exception as exc:
            logger.warning("Process list failed (%s).", type(exc).__name__)
            return self._processes
        rows.sort(key=lambda row: (row["cpu"], row["mem"]), reverse=True)
        self._processes = rows[:TOP_PROCESSES]
        return self._processes
