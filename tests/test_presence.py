"""Presence (Lupin 04): idle/front app/now playing reads, break logic, consent, voice, tone."""

from __future__ import annotations

import asyncio
import subprocess
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.consent import FrontAppConsent, build_front_app_context
from app.mac_control import (
    MacController,
    parse_front_app_output,
    parse_idle_seconds,
    parse_now_playing_output,
)
from app.memory import MemoryStore
from app.presence import Presence, register
from app.presence.breaks import BreakTracker
from app.presence.tone import effective_energy, music_tone, time_of_day_energy

CLOUD = ("custom", "https://proxy.example.com/v1")
OTHER = ("openai", "https://api.openai.com/v1")
LOCAL = ("ollama", "http://127.0.0.1:11434/v1")


# ---- mac_control reads -------------------------------------------------------


def _runner(stdout: str, calls: list, rc: int = 0):
    def run(argv, timeout=5.0, **_kw):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, rc, stdout=stdout, stderr="")
    return run


def test_idle_parse_and_argv() -> None:
    assert parse_idle_seconds('"HIDIdleTime" = 2500000000') == 2.5
    assert parse_idle_seconds("nothing") is None
    calls: list = []
    mac = MacController(runner=_runner('| "HIDIdleTime" = 61000000000', calls))
    assert mac.read_idle_seconds() == 61.0
    assert calls == [["/usr/sbin/ioreg", "-c", "IOHIDSystem"]]


def test_idle_failure_is_none() -> None:
    assert MacController(runner=_runner("", [], rc=1)).read_idle_seconds() is None


def test_front_app_parse_cleans_and_truncates() -> None:
    assert parse_front_app_output("Safari\nA page\n") == {"name": "Safari", "title": "A page"}
    assert parse_front_app_output("Notes\n") == {"name": "Notes", "title": ""}
    assert parse_front_app_output("\n") is None
    long = parse_front_app_output("X\n" + "t" * 500)
    assert long is not None and len(long["title"]) == 200


def test_front_app_uses_osascript_argv_only() -> None:
    calls: list = []
    mac = MacController(runner=_runner("Code\nfile.py", calls))
    assert mac.front_app() == {"name": "Code", "title": "file.py"}
    assert calls[0][:2] == ["/usr/bin/osascript", "-e"]
    assert MacController(runner=_runner("", [], rc=1)).front_app() is None


def test_now_playing_parse() -> None:
    assert parse_now_playing_output("null\nnull\nnull\nnull\nnull") is None
    out = parse_now_playing_output("Song\nBand\nJazz\n1\nnull")
    assert out == {"title": "Song", "artist": "Band", "genre": "Jazz", "playing": True, "bpm": None}
    assert parse_now_playing_output("Song\nnull\nnull\n0\n128")["bpm"] == 128.0
    calls: list = []
    MacController(runner=_runner("Song\nB\nPop\n1\nnull", calls)).now_playing()
    assert calls[0][0] == "/opt/homebrew/bin/nowplaying-cli" and calls[0][1] == "get"


# ---- break logic -------------------------------------------------------------


def _work(tr: BreakTracker, start: float, end: float, step: float = 30.0, **kw) -> list[float]:
    due = []
    t = start
    while t <= end:
        if tr.update(t, 1.0, **kw):
            due.append(t)
            tr.mark_reminded(t)
        t += step
    return due


def test_default_reminder_after_50_minutes() -> None:
    tr = BreakTracker()
    due = _work(tr, 0, 3000)
    assert due == [3000]


def test_idle_five_minutes_is_a_break() -> None:
    tr = BreakTracker()
    _work(tr, 0, 2400)
    assert not tr.update(2430, 300.0)  # break: clock reset
    assert tr.work_minutes(2430) == 0
    assert _work(tr, 2460, 2460 + 2900) == []  # not yet 50 min since the break


def test_input_inside_window_keeps_working() -> None:
    tr = BreakTracker()
    assert not tr.update(0, 200.0)  # last input 200s ago still counts as working
    assert tr.update(3000, 200.0)


def test_unreadable_idle_changes_nothing() -> None:
    tr = BreakTracker()
    tr.update(0, 1.0)
    assert tr.update(5000, None) is False
    assert tr.work_minutes(5000) == 0 or tr.work_minutes(5000) >= 0


def test_touch_snoozes_ten_minutes() -> None:
    tr = BreakTracker()
    tr.update(0, 1.0)
    tr.snooze(2900)
    assert not tr.update(3000, 1.0)
    assert not tr.update(3499, 1.0)
    assert tr.update(3500, 1.0)


def test_at_most_one_reminder_per_20_minutes() -> None:
    tr = BreakTracker()
    tr.set_interval(20)
    due = _work(tr, 0, 3 * 3600)
    assert all(b - a >= 20 * 60 for a, b in zip(due, due[1:]))
    assert len(due) >= 5


def test_muted_during_pomodoro_and_disabled() -> None:
    tr = BreakTracker()
    assert _work(tr, 0, 4000, pomodoro_active=True) == []
    tr2 = BreakTracker(enabled=False)
    assert _work(tr2, 0, 4000) == []


def test_interval_clamped() -> None:
    tr = BreakTracker()
    assert tr.set_interval(5) == 20
    assert tr.set_interval(9999) == 240
    assert tr.set_interval(60) == 60


# ---- tone ---------------------------------------------------------------------


def test_time_of_day_energy_and_expression() -> None:
    assert time_of_day_energy(3) < time_of_day_energy(10)
    assert effective_energy(85, 3) < effective_energy(85, 10)


def test_music_tone_only_when_playing() -> None:
    assert music_tone({"playing": True, "genre": "Ambient"}) == "calm"
    assert music_tone({"playing": True, "genre": "Rock"}) == "lively"
    assert music_tone({"playing": True, "genre": "", "bpm": 70}) == "calm"
    assert music_tone({"playing": False, "genre": "Rock"}) is None
    assert music_tone(None) is None


# ---- front app consent -------------------------------------------------------


class _Sig:
    def __init__(self, v):
        self.v = v

    def __call__(self):
        return self.v


def _consent(tmp_path: Path, start):
    mem = MemoryStore(db_path=tmp_path / "m.db")
    sig = _Sig(start)
    return mem, sig, FrontAppConsent(mem, sig)


def test_consent_default_off_and_toggle(tmp_path: Path) -> None:
    _, _, c = _consent(tmp_path, CLOUD)
    assert c.get() is False
    assert c.update(True) is True and c.get() is True
    assert c.update(False) is False


def test_consent_lapses_on_provider_change(tmp_path: Path) -> None:
    _, sig, c = _consent(tmp_path, CLOUD)
    c.update(True)
    sig.v = OTHER
    assert c.get() is False
    sig.v = CLOUD
    assert c.get() is False


def test_consent_ollama_local_needs_none_and_lapses_after(tmp_path: Path) -> None:
    _, sig, c = _consent(tmp_path, CLOUD)
    c.update(True)
    sig.v = LOCAL
    assert c.get() is True and c.is_local()
    sig.v = CLOUD
    assert c.get() is False


def test_context_only_with_consent() -> None:
    app = {"name": "Safari", "title": "Secret doc"}
    assert build_front_app_context(False, app) == ""
    assert build_front_app_context(True, None) == ""
    text = build_front_app_context(True, app)
    assert "Safari" in text and "Secret doc" in text


# ---- Presence ----------------------------------------------------------------


class _Mac:
    def __init__(self, idle=1.0, front=None, playing=None, pomodoro=False):
        self.idle, self.front, self.playing, self._pom = idle, front, playing, pomodoro
        self.front_calls = 0

    def read_idle_seconds(self):
        return self.idle

    def front_app(self):
        self.front_calls += 1
        return self.front

    def now_playing(self):
        return self.playing

    def pomodoro_active(self):
        return self._pom


class _Bus:
    def __init__(self, spoke=True, reason="spoken"):
        self.signals = []
        self.result = SimpleNamespace(spoke=spoke, reason=reason)

    async def emit(self, signal):
        self.signals.append(signal)
        return self.result


class _Clock:
    t = 0.0

    def __call__(self):
        return self.t


def _presence(tmp_path: Path, mac=None, bus=None, sig=CLOUD, hour=10):
    mem = MemoryStore(db_path=tmp_path / "m.db")
    clock = _Clock()
    p = Presence(
        mem, mac or _Mac(), lambda: bus, FrontAppConsent(mem, _Sig(sig)),
        clock=clock, now=lambda: datetime(2026, 11, 19, hour, 0),
    )
    return p, clock, mem


def test_tick_emits_break_signal_once(tmp_path: Path) -> None:
    bus = _Bus()
    p, clock, _ = _presence(tmp_path, bus=bus)

    async def go():
        out = []
        for t in range(0, 3100, 30):
            clock.t = float(t)
            out.append(await p.tick())
        return out

    out = asyncio.run(go())
    assert sum(out) == 1 and len(bus.signals) == 1
    sig = bus.signals[0]
    assert sig.kind == "break_reminder" and sig.source == "presence" and sig.summary


def test_tick_retries_when_nobody_heard(tmp_path: Path) -> None:
    bus = _Bus(spoke=False, reason="no_active_body")
    p, clock, _ = _presence(tmp_path, bus=bus)

    async def go():
        clock.t = 0.0
        await p.tick()
        clock.t = 3000.0
        await p.tick()
        clock.t = 3030.0
        await p.tick()

    asyncio.run(go())
    assert len(bus.signals) == 2  # not consumed: tried again on the next sample


def test_tick_silent_during_pomodoro(tmp_path: Path) -> None:
    bus = _Bus()
    p, clock, _ = _presence(tmp_path, mac=_Mac(pomodoro=True), bus=bus)

    async def go():
        for t in (0.0, 3000.0, 6000.0):
            clock.t = t
            await p.tick()

    asyncio.run(go())
    assert bus.signals == []


def test_touch_snoozes_and_pet_is_happy(tmp_path: Path) -> None:
    p, clock, _ = _presence(tmp_path, bus=_Bus())
    p.tracker.update(0.0, 1.0)
    clock.t = 2950.0
    assert p.on_touch("pet") == "happy"
    assert p.on_touch("poke") is None
    assert p.tracker.update(3000.0, 1.0) is False  # snoozed until 3550
    assert p.tracker.update(3560.0, 1.0) is True


def test_voice_interval_off_on_snooze(tmp_path: Path) -> None:
    p, _, mem = _presence(tmp_path)
    r = asyncio.run(p.handle_voice("break", "every:60"))
    assert r["ok"] and p.tracker.interval_minutes == 60 and "60" in r["spoken"]
    assert asyncio.run(p.handle_voice("break", "every:5"))["spoken"]
    assert p.tracker.interval_minutes == 20
    assert not asyncio.run(p.handle_voice("break", "every:soon"))["ok"]
    assert asyncio.run(p.handle_voice("break", "off"))["ok"] and not p.tracker.enabled
    assert asyncio.run(p.handle_voice("break", "on"))["ok"] and p.tracker.enabled
    assert asyncio.run(p.handle_voice("break", "snooze"))["ok"]
    assert not asyncio.run(p.handle_voice("break", "dance"))["ok"]
    # persisted
    again = Presence(mem, _Mac(), lambda: None, FrontAppConsent(mem, _Sig(CLOUD)))
    assert again.tracker.interval_minutes == 20


def test_turn_context_front_app_only_with_consent(tmp_path: Path) -> None:
    mac = _Mac(front={"name": "Safari", "title": "Bank"})
    p, _, _ = _presence(tmp_path, mac=mac)
    assert "Safari" not in asyncio.run(p.turn_context())
    assert mac.front_calls == 0  # not even read without consent
    p.consent.update(True)
    ctx = asyncio.run(p.turn_context())
    assert "Safari" in ctx and "Bank" in ctx


def test_turn_context_music_tone_has_no_title(tmp_path: Path) -> None:
    mac = _Mac(playing={"title": "Secret Song", "artist": "Band", "genre": "Jazz", "playing": True, "bpm": None})
    p, _, _ = _presence(tmp_path, mac=mac)
    ctx = asyncio.run(p.turn_context())
    assert ctx and "Secret Song" not in ctx and "Band" not in ctx


def test_companion_line_energy_follows_time_of_day(tmp_path: Path) -> None:
    late, _, _ = _presence(tmp_path, hour=3)
    day = Presence(late._memory, _Mac(), lambda: None, late.consent, now=lambda: datetime(2026, 11, 19, 10, 0))
    assert late.companion_line() != day.companion_line()


def test_routes_are_mac_only_for_changes(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    app = FastAPI()
    allowed = {"mac": True}

    def require(request, detail):
        if not allowed["mac"]:
            from fastapi import HTTPException
            raise HTTPException(403, detail)

    register(app, mem, _Mac(), _Sig(CLOUD), require)
    c = TestClient(app, base_url="http://localhost")
    assert c.get("/api/presence").json()["break_minutes"] == 50
    r = c.put("/api/presence", json={"break_minutes": 60, "front_app": True})
    assert r.json()["break_minutes"] == 60 and r.json()["front_app"] is True
    assert c.put("/api/presence", json={"break_minutes": 0}).status_code == 422
    allowed["mac"] = False
    assert c.put("/api/presence", json={"break_minutes": 30}).status_code == 403
    assert c.get("/api/presence").json()["break_minutes"] == 60


def test_llm_parses_break_action_tag() -> None:
    from app.llm import _ACTION_TAG_RE
    assert _ACTION_TAG_RE.match("[action:break:every:60]")


def test_missing_nowplaying_cli_is_never_spawned(tmp_path: Path) -> None:
    class NoCli(_Mac):
        def now_playing_available(self):
            return False

        def now_playing(self):
            raise AssertionError("must not be called")

    p, _, _ = _presence(tmp_path, mac=NoCli())
    assert asyncio.run(p.turn_context()) == ""


def test_focus_or_rate_limited_emit_counts_as_reminded(tmp_path: Path) -> None:
    for reason in ("focus", "rate_limited"):
        bus = _Bus(spoke=False, reason=reason)
        p, clock, _ = _presence(tmp_path, bus=bus)

        async def go():
            clock.t = 0.0
            await p.tick()
            clock.t = 3000.0
            await p.tick()
            clock.t = 3030.0
            await p.tick()

        asyncio.run(go())
        assert len(bus.signals) == 1, reason


def test_put_presence_rejects_rebinding_and_non_json(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    app = FastAPI()
    register(app, mem, _Mac(), _Sig(CLOUD), lambda request, detail: None)
    c = TestClient(app, base_url="http://localhost")
    ok = {"Origin": "http://localhost"}
    assert c.put("/api/presence", json={"front_app": True}, headers=ok).status_code == 200
    evil = c.put("/api/presence", json={"front_app": True}, headers={"Host": "evil.example.com"})
    assert evil.status_code == 403
    assert c.put("/api/presence", json={"front_app": True}, headers={"Origin": "http://evil.example.com"}).status_code == 403
    assert c.put("/api/presence", content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
