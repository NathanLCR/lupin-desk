"""Local mode: Ollama on a loopback host skips Data Consent, and the slow-model notice."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app import speech_en, speech_pt_br
from app.consent import DataConsent, is_local_provider
from app.local_mode import SlowModelNotice
from app.memory import MemoryStore

OLLAMA_LOCAL = ("ollama", "http://127.0.0.1:11434/v1")
CLOUD = ("openai", "https://api.openai.com/v1")


# ---------------------------------------------------------------------------
# is_local_provider
# ---------------------------------------------------------------------------


def test_is_local_provider_truth_table() -> None:
    assert is_local_provider("ollama", "http://127.0.0.1:11434/v1") is True
    assert is_local_provider("ollama", "http://localhost:11434/v1") is True
    assert is_local_provider("ollama", "http://[::1]:11434/v1") is True
    assert is_local_provider(" Ollama ", "http://127.0.0.1:11434/v1") is True
    assert is_local_provider("ollama", "http://192.168.1.20:11434/v1") is False
    assert is_local_provider("custom", "http://127.0.0.1:8080/v1") is False
    assert is_local_provider("local_proxy", "http://127.0.0.1:31415/v1") is False
    assert is_local_provider("openai", "https://api.openai.com/v1") is False
    assert is_local_provider("openai", "http://127.0.0.1:11434/v1") is False
    assert is_local_provider("ollama", "") is False


# ---------------------------------------------------------------------------
# DataConsent with the Ollama exception
# ---------------------------------------------------------------------------


def test_ollama_loopback_has_consent_without_writing(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    try:
        consent = DataConsent(mem, lambda: OLLAMA_LOCAL)
        assert consent.is_local() is True
        assert consent.get() == {"calendar": True, "email": True}
        assert consent.update(calendar=False) == {"calendar": True, "email": True}
        assert consent.get() == {"calendar": True, "email": True}
        assert mem.get_meta("data_consent") is None, "local mode must not write the meta store"
    finally:
        mem.close()


def test_cloud_provider_default_is_off_and_unchanged(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    try:
        consent = DataConsent(mem, lambda: CLOUD)
        assert consent.is_local() is False
        assert consent.get() == {"calendar": False, "email": False}
        assert consent.update(email=True) == {"calendar": False, "email": True}
        assert consent.get() == {"calendar": False, "email": True}
    finally:
        mem.close()


def test_cloud_consent_does_not_survive_a_round_trip_through_ollama(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "m.db")
    try:
        sig = [CLOUD]
        consent = DataConsent(mem, lambda: sig[0])
        consent.update(calendar=True, email=True)
        assert consent.get() == {"calendar": True, "email": True}

        sig[0] = OLLAMA_LOCAL
        assert consent.get() == {"calendar": True, "email": True}

        sig[0] = CLOUD
        assert consent.get() == {"calendar": False, "email": False}
    finally:
        mem.close()


# ---------------------------------------------------------------------------
# SlowModelNotice
# ---------------------------------------------------------------------------


async def test_slow_notice_fires_after_delay_if_not_stopped() -> None:
    calls: list[str] = []

    async def on_slow() -> None:
        calls.append("slow")

    notice = SlowModelNotice(0.05, on_slow)
    notice.start()
    await asyncio.sleep(0.15)
    assert calls == ["slow"]
    assert notice.fired is True


async def test_slow_notice_does_not_fire_when_stopped_before_delay() -> None:
    calls: list[str] = []

    async def on_slow() -> None:
        calls.append("slow")

    notice = SlowModelNotice(0.05, on_slow)
    notice.start()
    notice.stop()
    await asyncio.sleep(0.15)
    assert calls == []
    assert notice.fired is False


async def test_slow_notice_stop_is_idempotent_and_safe_before_start() -> None:
    async def on_slow() -> None:
        return None

    notice = SlowModelNotice(0.05, on_slow)
    notice.stop()
    notice.stop()
    notice.start()
    notice.stop()
    notice.stop()
    assert notice.fired is False


async def test_slow_notice_stop_after_firing_is_safe() -> None:
    calls: list[str] = []

    async def on_slow() -> None:
        calls.append("slow")

    notice = SlowModelNotice(0.01, on_slow)
    notice.start()
    await asyncio.sleep(0.05)
    notice.stop()
    notice.stop()
    assert calls == ["slow"]
    assert notice.fired is True


async def test_slow_notice_with_zero_delay_never_fires() -> None:
    calls: list[str] = []

    async def on_slow() -> None:
        calls.append("slow")

    notice = SlowModelNotice(0, on_slow)
    notice.start()
    await asyncio.sleep(0.05)
    notice.stop()
    assert calls == []
    assert notice.fired is False


async def test_slow_notice_swallows_callback_errors() -> None:
    async def on_slow() -> None:
        raise RuntimeError("boom")

    notice = SlowModelNotice(0.01, on_slow)
    notice.start()
    await asyncio.sleep(0.05)
    notice.stop()
    assert notice.fired is True


async def test_slow_notice_start_is_idempotent() -> None:
    calls: list[str] = []

    async def on_slow() -> None:
        calls.append("slow")

    notice = SlowModelNotice(0.02, on_slow)
    notice.start()
    notice.start()
    await asyncio.sleep(0.08)
    assert calls == ["slow"]


# ---------------------------------------------------------------------------
# Speech constants
# ---------------------------------------------------------------------------


def test_local_model_slow_exists_in_both_languages() -> None:
    assert speech_pt_br.LOCAL_MODEL_SLOW
    assert speech_en.LOCAL_MODEL_SLOW
