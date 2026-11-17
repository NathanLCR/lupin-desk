"""Testes automatizados para CoworkStore (somente leitura), TodayEngine e FirstWake."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.cowork import CoworkError, CoworkStore
from app.main import create_app
from app.memory import MemoryStore
from app.today import (
    FirstWakeTracker,
    TodayEngine,
    ValidationContext,
    build_deterministic_fallback,
    validate_today_summary,
)


def _seed_cowork(tmp_path: Path) -> Path:
    ws = tmp_path / "Cowork"
    state_dir = ws / "state"
    app_dir = ws / "app"
    state_dir.mkdir(parents=True)
    app_dir.mkdir(parents=True)

    (state_dir / "tasks.yaml").write_text(
        "- id: t-001\n  title: Revisar intro\n  domain: dissertation\n  status: open\n  due: 2026-11-16\n",
        encoding="utf-8",
    )
    (state_dir / "deadlines.yaml").write_text(
        "- id: d-001\n  title: Entrega parcial\n  date: 2026-11-30\n  domain: dissertation\n  hard: false\n",
        encoding="utf-8",
    )
    (state_dir / "schedule.yaml").write_text(
        "week_of: 2026-11-16\nshifts: []\n",
        encoding="utf-8",
    )
    (app_dir / "actions.yaml").write_text(
        "actions:\n"
        "  - id: echo_read\n"
        "    title: Read check\n"
        "    risk: read\n"
        "    argv: ['/bin/echo', 'ok-read']\n"
        "  - id: echo_write\n"
        "    title: Write sync\n"
        "    risk: write\n"
        "    argv: ['/bin/echo', 'ok-write']\n",
        encoding="utf-8",
    )
    return ws


def test_cowork_store_confinement_e_leitura(tmp_path: Path) -> None:
    ws = _seed_cowork(tmp_path)
    store = CoworkStore(ws)

    with pytest.raises(CoworkError):
        store._resolve_state_file("../secrets.yaml")

    state = store.load_state()
    assert state["workspace_exists"] is True
    assert state["sync_status"] == "green"
    assert state["open_tasks_count"] == 1

    prompt_ctx = store.build_prompt_context()
    assert "t-001: Revisar intro" in prompt_ctx
    assert "d-001: Entrega parcial" in prompt_ctx


def test_today_anti_hallucination_validator() -> None:
    ctx = ValidationContext(
        allowed_ids={"t-001", "d-001"},
        allowed_iso_dates={"2026-11-16", "2026-11-30"},
        allowed_numbers={1},
        input_text="TODAY: 2026-11-16\nOPEN_TASKS_COUNT: 1\n- t-001 Revisar intro (due 2026-11-16)",
    )

    valid_json = json.dumps(
        {
            "headline": "Hoje (2026-11-16): 1 tarefa aberta.",
            "top": [{"id": "t-001", "why": "Vence em 2026-11-16."}],
            "warnings": [],
        }
    )
    assert validate_today_summary(valid_json, ctx)["is_valid"] is True

    bad_id = json.dumps(
        {
            "headline": "Hoje (2026-11-16): 1 tarefa.",
            "top": [{"id": "t-999", "why": "Inventada."}],
            "warnings": [],
        }
    )
    assert validate_today_summary(bad_id, ctx)["is_valid"] is False

    bad_number_word = json.dumps(
        {
            "headline": "Hoje (2026-11-16): 1 tarefa.",
            "top": [{"id": "t-001", "why": "three items pending"}],
            "warnings": [],
        }
    )
    assert validate_today_summary(bad_number_word, ctx)["is_valid"] is False


def test_first_wake_tracker_daily_reset(tmp_path: Path) -> None:
    mem = MemoryStore(db_path=tmp_path / "mem.db")
    try:
        tracker = FirstWakeTracker(mem)
        assert tracker.should_trigger_today("2026-11-16") is True
        tracker.mark_triggered("2026-11-16")
        assert tracker.should_trigger_today("2026-11-16") is False
        assert tracker.should_trigger_today("2026-11-17") is True
    finally:
        mem.close()


def test_first_wake_route(tmp_path: Path) -> None:
    ws = _seed_cowork(tmp_path)
    settings = Settings(db_path=tmp_path / "mem.db", cowork_workspace_path=ws)
    mem = MemoryStore(db_path=tmp_path / "app.db")
    app = create_app(settings=settings, memory_store=mem)
    try:
        with TestClient(app) as tc:
            # O First Wake agora é falado por Lupin no WebSocket (tests/test_first_wake.py).
            assert tc.get("/api/first-wake").status_code == 404
            assert tc.get("/api/jarvis/first-wake").status_code == 404
    finally:
        mem.close()
