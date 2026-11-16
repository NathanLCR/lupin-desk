"""Testes automatizados para CoworkStore, ActionsRunner, TodayEngine, FirstWake e Jarvis."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.cowork import ActionsRunner, CoworkError, CoworkStore
from app.llm import LLMClient
from app.mac_control import MacController
from app.main import create_app
from app.memory import MemoryStore
from app.shortcuts import ShortcutStore
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


def test_cowork_store_confinement_diff_and_backup(tmp_path: Path) -> None:
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

    preview = store.preview_capture("add_task", {"title": "Nova tarefa", "domain": "personal"})
    assert preview["target_file"] == "state/tasks.yaml"
    assert "t-002" in preview["diff"]
    assert "t-002" not in (ws / "state" / "tasks.yaml").read_text(encoding="utf-8")

    applied = store.apply_capture(preview["approval_id"])
    assert applied["ok"] is True
    assert applied["backup_path"] is not None
    assert Path(applied["backup_path"]).exists()
    assert "t-002" in (ws / "state" / "tasks.yaml").read_text(encoding="utf-8")


def test_actions_runner_read_vs_write_gate(tmp_path: Path) -> None:
    ws = _seed_cowork(tmp_path)
    runner = ActionsRunner(ws)

    read_res = runner.prepare_run("echo_read")
    assert read_res["executed"] is True
    assert read_res["ok"] is True
    assert "ok-read" in read_res["stdout"]

    write_res = runner.prepare_run("echo_write")
    assert write_res["executed"] is False
    assert write_res["requires_approval"] is True
    assert write_res["risk"] == "write"

    applied = runner.apply_action(write_res["approval_id"])
    assert applied["executed"] is True
    assert applied["ok"] is True
    assert "ok-write" in applied["stdout"]


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


def test_mac_controller_on_demand_vision_and_clipboard(tmp_path: Path) -> None:
    calls: list[list[str]] = []

    def fake_run(argv: list[str], timeout: float = 10.0) -> subprocess.CompletedProcess[str]:
        calls.append(list(argv))
        if argv[0] == "/usr/sbin/screencapture":
            Path(argv[-1]).write_bytes(b"\x89PNG\r\n\x1a\nfake")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[0] == "/usr/bin/pbpaste":
            return subprocess.CompletedProcess(argv, 0, stdout="texto copiado", stderr="")
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr="unexpected")

    ctrl = MacController(runner=fake_run)
    snap = ctrl.capture_screen_b64()
    assert snap["ok"] is True
    assert snap["mime_type"] == "image/png"
    assert not Path(calls[0][-1]).exists()

    clip = ctrl.read_clipboard_text()
    assert clip["ok"] is True
    assert clip["text"] == "texto copiado"


def test_llm_multimodal_payload_and_ws_cowork_approval(tmp_path: Path) -> None:
    ws = _seed_cowork(tmp_path)
    settings = Settings(db_path=tmp_path / "mem.db", cowork_workspace_path=ws)

    client = LLMClient(settings)
    payload = client._build_payload(
        user_text="Olha minha tela",
        history=[],
        image_b64="ZmFrZQ==",
    )
    last_msg = payload["messages"][-1]
    assert isinstance(last_msg["content"], list)
    assert last_msg["content"][1]["image_url"]["url"] == "data:image/png;base64,ZmFrZQ=="

    async def fake_stream(**_kwargs: Any):
        yield {"type": "emotion", "emotion": "happy"}
        yield {"type": "action", "kind": "cowork", "target": "add_task:Enviar capítulo"}
        yield {"type": "result", "text": "Posso adicionar essa tarefa?", "raw_text": "", "emotion": "happy"}

    mem = MemoryStore(db_path=tmp_path / "app.db")
    shortcuts = ShortcutStore(db_path=tmp_path / "app.db")
    cowork = CoworkStore(ws)
    app = create_app(
        settings=settings,
        memory_store=mem,
        llm_client=LLMClient(settings, stream_fn=fake_stream),
        shortcut_store=shortcuts,
        cowork_store=cowork,
        actions_runner=ActionsRunner(ws),
        today_engine=TodayEngine(settings, cowork),
    )

    try:
        with TestClient(app) as tc:
            with tc.websocket_connect("/ws") as ws_conn:
                ws_conn.send_json({"type": "text", "text": "adiciona tarefa enviar capítulo"})
                events = []
                for _ in range(5):
                    ev = ws_conn.receive_json()
                    events.append(ev)
                    if ev.get("type") == "done":
                        break

                approval_ev = next((e for e in events if e.get("type") == "tool_approval_request"), None)
                assert approval_ev is not None
                assert approval_ev["kind"] == "cowork_capture"
                assert approval_ev["risk"] == "write"
                assert "Enviar capítulo" in approval_ev["diff"]

                ws_conn.send_json(
                    {
                        "type": "confirm_action",
                        "approval_id": approval_ev["approval_id"],
                        "approved": True,
                    }
                )
                exec_ev = None
                for _ in range(5):
                    ev = ws_conn.receive_json()
                    if ev.get("type") == "action_executed":
                        exec_ev = ev
                        break
                assert exec_ev is not None
                assert exec_ev["ok"] is True
                assert "Enviar capítulo" in (ws / "state" / "tasks.yaml").read_text(encoding="utf-8")
    finally:
        shortcuts.close()
        mem.close()
