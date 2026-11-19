"""The hold option for Signals (patch .scratch/agents/patches/p09-signals.py.diff).

Until the orchestrator applies the patch, these tests apply it to a temporary copy of
app/signals.py and import that copy, so they check the patch itself. Once app/signals.py already
has the option they test it directly.
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
PATCH = ROOT / ".scratch" / "agents" / "patches" / "p09-signals.py.diff"


@pytest.fixture(scope="module")
def sig(tmp_path_factory):
    source = ROOT / "app" / "signals.py"
    if "hold_expression" in source.read_text(encoding="utf-8"):
        from app import signals

        return signals
    if not PATCH.exists():
        pytest.skip("patch already applied or removed")
    work = tmp_path_factory.mktemp("signals_patch")
    (work / "app").mkdir()
    shutil.copy(source, work / "app" / "signals.py")
    subprocess.run(["git", "apply", str(PATCH)], cwd=work, check=True)
    spec = importlib.util.spec_from_file_location("signals_patched", work / "app" / "signals.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["signals_patched"] = module
    spec.loader.exec_module(module)
    return module


class Recorder:
    def __init__(self):
        self.expressions: list[str] = []
        self.spoken: list[str] = []

    async def set_expression(self, name):
        self.expressions.append(name)

    async def speak(self, text):
        self.spoken.append(text)


def make_bus(sig, rec, now=None, **kwargs):
    clock = now or (lambda: 1000.0)
    return sig.SignalBus(None, speak=rec.speak, set_expression=rec.set_expression, clock=clock, **kwargs)


def hold_signal(sig, hold_id="p1", kind="claude_code_needs_user"):
    return sig.Signal(kind=kind, source="claude_code", hold_expression=True, id=hold_id)


def test_hold_keeps_expression_and_release_returns_to_neutral(sig):
    rec = Recorder()
    bus = make_bus(sig, rec)

    async def run():
        await bus.emit(hold_signal(sig))
        assert rec.expressions == ["curious"]
        # While held, another signal does not change the expression.
        await bus.emit(sig.Signal(kind="timer_done", source="timer"))
        assert rec.expressions == ["curious"]
        assert await bus.release(id="p1") == 1
        assert rec.expressions == ["curious", "neutral"]

    asyncio.run(run())


def test_hold_ignores_the_speaking_rate_limit_but_speech_stays_limited(sig):
    rec = Recorder()
    bus = make_bus(sig, rec)

    async def run():
        first = await bus.emit(hold_signal(sig, "a"))
        second = await bus.emit(hold_signal(sig, "b"))
        assert first.spoke and not second.spoke
        assert second.reason == "rate_limited"
        assert rec.expressions == ["curious", "curious"]
        assert await bus.release(id="a") == 1
        assert rec.expressions[-1] == "curious"  # b still holds: no neutral yet
        assert await bus.release(kind="claude_code_needs_user") == 1
        assert rec.expressions[-1] == "neutral"

    asyncio.run(run())


def test_release_of_unknown_hold_does_nothing_and_needs_a_selector(sig):
    rec = Recorder()
    bus = make_bus(sig, rec)

    async def run():
        assert await bus.release(id="nope") == 0
        assert rec.expressions == []
        with pytest.raises(ValueError):
            await bus.release()

    asyncio.run(run())


def test_clear_expression_callback_is_used_when_given(sig):
    rec = Recorder()
    cleared = []

    async def clear():
        cleared.append(True)

    bus = make_bus(sig, rec, clear_expression=clear)

    async def run():
        await bus.emit(hold_signal(sig))
        await bus.release(id="p1")

    asyncio.run(run())
    assert cleared == [True]
    assert rec.expressions == ["curious"]


def test_signals_without_hold_behave_as_before(sig):
    rec = Recorder()
    bus = make_bus(sig, rec)

    async def run():
        result = await bus.emit(sig.Signal(kind="timer_done", source="timer"))
        assert result.spoke and rec.expressions == ["happy"]
        await bus.emit(sig.Signal(kind="habit_due", source="x"))
        assert rec.expressions == ["happy", "curious"]

    asyncio.run(run())
