"""Tests for the productivity REST routes, the Panel actions and register()."""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.actions import ActionRegistry
from app.productivity import Productivity, register

FIXED_NOW = datetime(2026, 11, 18, 9, 0, 0)  # a Wednesday


class FakeHub:
    """Stands in for DeviceHub: records every publish."""

    def __init__(self) -> None:
        self.published: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, topic: str, payload: dict[str, Any]) -> int:
        self.published.append((topic, payload))
        return 1

    def topics(self) -> list[str]:
        return [topic for topic, _ in self.published]


def _app(tmp_path: Path) -> tuple[FastAPI, FakeHub, Productivity]:
    app = FastAPI()
    app.state.actions = ActionRegistry()
    hub = FakeHub()
    app.state.device_hub = hub
    productivity = register(app, tmp_path / "p.db", clock=lambda: FIXED_NOW)
    return app, hub, productivity


def _run(app: FastAPI, action_id: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    return asyncio.run(app.state.actions.run(action_id, args))


# ----------------------------------------------------------------- tasks


def test_task_routes_happy_path_and_payload_shape(tmp_path: Path) -> None:
    app, _, _ = _app(tmp_path)
    client = TestClient(app)

    created = client.post("/api/tasks", json={"title": "  buy   milk "})
    assert created.status_code == 200
    task = created.json()
    assert task == {
        "id": task["id"],
        "title": "buy milk",
        "done": False,
        "created_at": "2026-11-18T09:00:00",
        "done_at": None,
    }

    assert client.get("/api/tasks").json() == {"tasks": [task]}

    done = client.patch(f"/api/tasks/{task['id']}", json={"done": True})
    assert done.status_code == 200
    assert done.json()["done"] is True
    assert done.json()["done_at"] == "2026-11-18T09:00:00"

    assert client.get("/api/tasks").json() == {"tasks": []}
    assert client.get("/api/tasks?include_done=false").json() == {"tasks": []}
    assert [t["id"] for t in client.get("/api/tasks?include_done=true").json()["tasks"]] == [
        task["id"]
    ]

    reopened = client.patch(f"/api/tasks/{task['id']}", json={"done": False})
    assert reopened.json()["done"] is False
    assert reopened.json()["done_at"] is None

    deleted = client.delete(f"/api/tasks/{task['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"ok": True}
    assert client.get("/api/tasks?include_done=true").json() == {"tasks": []}


def test_task_routes_errors(tmp_path: Path) -> None:
    app, _, _ = _app(tmp_path)
    client = TestClient(app)

    assert client.post("/api/tasks", json={"title": "   "}).status_code == 422
    assert client.post("/api/tasks", json={"title": "x" * 201}).status_code == 422
    assert client.post("/api/tasks", json={}).status_code == 422

    created = client.post("/api/tasks", json={"title": "keep me"}).json()
    assert client.patch(f"/api/tasks/{created['id']}", json={}).status_code == 422
    assert client.patch(f"/api/tasks/{created['id']}", json={"done": None}).status_code == 422
    assert client.patch("/api/tasks/9999", json={"done": True}).status_code == 404
    assert client.delete("/api/tasks/9999").status_code == 404


def test_task_mutations_publish_full_list_and_failures_publish_nothing(tmp_path: Path) -> None:
    app, hub, _ = _app(tmp_path)
    client = TestClient(app)

    first = client.post("/api/tasks", json={"title": "first"}).json()
    assert hub.published[-1] == ("tasks", {"tasks": [first]})

    client.post("/api/tasks", json={"title": "second"})
    second_payload = hub.published[-1][1]["tasks"]
    assert [t["title"] for t in second_payload] == ["first", "second"]

    client.patch(f"/api/tasks/{first['id']}", json={"done": True})
    assert hub.published[-1][0] == "tasks"
    assert [t["title"] for t in hub.published[-1][1]["tasks"]] == ["second"]

    client.delete(f"/api/tasks/{first['id']}")
    assert hub.topics()[-1] == "tasks"

    count = len(hub.published)
    client.delete("/api/tasks/9999")
    client.post("/api/tasks", json={"title": ""})
    client.patch("/api/tasks/9999", json={"done": True})
    assert len(hub.published) == count


# ----------------------------------------------------------------- notes


def test_note_routes_happy_path_and_errors(tmp_path: Path) -> None:
    app, hub, _ = _app(tmp_path)
    client = TestClient(app)

    created = client.post("/api/notes", json={"text": "  remember the tea  "})
    assert created.status_code == 200
    note = created.json()
    assert note == {
        "id": note["id"],
        "text": "remember the tea",
        "created_at": "2026-11-18T09:00:00",
    }
    assert client.get("/api/notes").json() == {"notes": [note]}
    assert hub.published[-1] == ("notes", {"notes": [note]})

    assert client.post("/api/notes", json={"text": ""}).status_code == 422
    assert client.post("/api/notes", json={"text": "n" * 2001}).status_code == 422
    assert client.post("/api/notes", json={"text": "n" * 2000}).status_code == 200

    assert client.delete(f"/api/notes/{note['id']}").json() == {"ok": True}
    assert hub.topics()[-1] == "notes"
    assert hub.published[-1][1] == {"notes": [t for t in client.get("/api/notes").json()["notes"]]}
    assert client.delete(f"/api/notes/{note['id']}").status_code == 404


# ---------------------------------------------------------------- habits


def test_habit_routes_happy_path_and_payload_shape(tmp_path: Path) -> None:
    app, hub, _ = _app(tmp_path)
    client = TestClient(app)

    created = client.post(
        "/api/habits", json={"name": "Stretch", "days": [0, 2], "time": "08:30"}
    )
    assert created.status_code == 200
    habit = created.json()
    assert habit["name"] == "Stretch"
    assert habit["days"] == [0, 2]
    assert habit["time"] == "08:30"
    assert habit["streak"] == 0
    assert habit["done_today"] is False
    assert hub.published[-1] == ("habits", {"habits": [habit]})

    assert client.get("/api/habits").json() == {"habits": [habit]}

    checked = client.post(f"/api/habits/{habit['id']}/checkin", json={})
    assert checked.status_code == 200
    assert checked.json()["done_today"] is True
    assert checked.json()["streak"] == 1
    assert hub.published[-1][0] == "habits"

    undone = client.post(f"/api/habits/{habit['id']}/checkin", json={"done": False})
    assert undone.json()["done_today"] is False
    assert undone.json()["streak"] == 0

    past = client.post(
        f"/api/habits/{habit['id']}/checkin", json={"day": "2026-11-16", "done": True}
    )
    assert past.status_code == 200
    assert past.json()["done_today"] is False

    assert client.delete(f"/api/habits/{habit['id']}").json() == {"ok": True}
    assert hub.topics()[-1] == "habits"
    assert client.delete(f"/api/habits/{habit['id']}").status_code == 404


def test_habit_routes_errors(tmp_path: Path) -> None:
    app, _, _ = _app(tmp_path)
    client = TestClient(app)

    habit = client.post("/api/habits", json={"name": "Read"}).json()
    assert habit["days"] == []
    assert habit["time"] is None

    assert client.post("/api/habits", json={"name": ""}).status_code == 422
    assert client.post("/api/habits", json={"name": "h" * 81}).status_code == 422
    assert client.post("/api/habits", json={"name": "x", "days": [7]}).status_code == 422
    assert client.post("/api/habits", json={"name": "x", "time": "25:00"}).status_code == 422

    checkin = f"/api/habits/{habit['id']}/checkin"
    assert client.post(checkin, json={"day": "18-11-2026"}).status_code == 422
    assert client.post(checkin, json={"day": "2026-13-01"}).status_code == 422
    assert client.post("/api/habits/9999/checkin", json={}).status_code == 404


# ------------------------------------------------------------- publishing


def test_publish_wrapper_is_lazy_and_failures_are_not_raised(tmp_path: Path) -> None:
    app = FastAPI()
    productivity = register(app, tmp_path / "p.db", clock=lambda: FIXED_NOW)
    client = TestClient(app)

    # No device_hub and no actions in state: routes still work.
    assert client.post("/api/tasks", json={"title": "solo"}).status_code == 200

    # Hub attached after register(): the next mutation reaches it.
    hub = FakeHub()
    app.state.device_hub = hub
    client.post("/api/notes", json={"text": "later"})
    assert hub.topics() == ["notes"]

    assert isinstance(productivity, Productivity)
    assert app.state.productivity is productivity
    assert getattr(app.state, "actions", None) is None


# ------------------------------------------------------------ panel actions


def test_six_action_ids_are_registered(tmp_path: Path) -> None:
    app, _, _ = _app(tmp_path)

    ids = [entry["id"] for entry in app.state.actions.list()]

    assert ids == [
        "habits.checkin",
        "notes.add",
        "notes.remove",
        "tasks.add",
        "tasks.remove",
        "tasks.toggle",
    ]


def test_task_actions_add_toggle_and_remove(tmp_path: Path) -> None:
    app, hub, _ = _app(tmp_path)

    added = _run(app, "tasks.add", {"title": "pay rent"})
    assert added["ok"] is True
    task = added["result"]
    assert task["title"] == "pay rent"
    assert hub.published[-1][0] == "tasks"

    toggled = _run(app, "tasks.toggle", {"id": task["id"]})
    assert toggled["result"]["done"] is True
    toggled_back = _run(app, "tasks.toggle", {"id": task["id"]})
    assert toggled_back["result"]["done"] is False
    explicit = _run(app, "tasks.toggle", {"id": task["id"], "done": True})
    assert explicit["result"]["done"] is True
    assert hub.topics()[-1] == "tasks"
    assert hub.published[-1][1] == {"tasks": []}

    removed = _run(app, "tasks.remove", {"id": task["id"]})
    assert removed == {
        "type": "action_result",
        "id": "tasks.remove",
        "ok": True,
        "result": {"id": task["id"], "removed": True},
    }
    assert _run(app, "tasks.remove", {"id": task["id"]})["ok"] is False
    assert _run(app, "tasks.toggle", {"id": task["id"]})["ok"] is False


def test_note_and_habit_actions(tmp_path: Path) -> None:
    app, hub, _ = _app(tmp_path)

    note = _run(app, "notes.add", {"text": "water the plants"})
    assert note["ok"] is True
    assert note["result"]["text"] == "water the plants"
    assert hub.topics()[-1] == "notes"

    removed = _run(app, "notes.remove", {"id": note["result"]["id"]})
    assert removed["result"] == {"id": note["result"]["id"], "removed": True}
    assert hub.topics()[-1] == "notes"
    assert _run(app, "notes.remove", {"id": note["result"]["id"]})["ok"] is False

    habit = TestClient(app).post("/api/habits", json={"name": "Walk"}).json()
    checked = _run(app, "habits.checkin", {"id": habit["id"]})
    assert checked["ok"] is True
    assert checked["result"]["done_today"] is True
    assert hub.topics()[-1] == "habits"

    unchecked = _run(app, "habits.checkin", {"id": habit["id"], "done": False})
    assert unchecked["result"]["done_today"] is False
    assert _run(app, "habits.checkin", {"id": 9999})["ok"] is False


def test_actions_reject_bad_arguments(tmp_path: Path) -> None:
    app, hub, _ = _app(tmp_path)
    count = len(hub.published)

    bad_calls = [
        ("tasks.add", {}),
        ("tasks.add", {"title": 5}),
        ("tasks.add", {"title": "  "}),
        ("tasks.toggle", {"id": "1"}),
        ("tasks.toggle", {"id": True}),
        ("tasks.toggle", {}),
        ("tasks.remove", {"id": None}),
        ("notes.add", {"text": ""}),
        ("notes.add", {"text": 3}),
        ("notes.remove", {"id": 9999}),
        ("habits.checkin", {}),
        ("habits.checkin", {"id": 1.5}),
    ]
    for action_id, args in bad_calls:
        reply = _run(app, action_id, args)
        assert reply["ok"] is False, (action_id, args)
        assert reply["error"] == "action_failed", (action_id, args)

    assert _run(app, "tasks.toggle", {"id": 1, "done": "yes"})["ok"] is False
    assert len(hub.published) == count


# ------------------------------------------------------------------ voice


def test_voice_task_add_shows_up_in_the_list(tmp_path: Path) -> None:
    app, hub, productivity = _app(tmp_path)

    reply = asyncio.run(productivity.handle_voice("task", "add:buy milk"))

    assert reply["ok"] is True
    assert reply["kind"] == "task"
    assert hub.topics()[-1] == "tasks"
    titles = [task["title"] for task in TestClient(app).get("/api/tasks").json()["tasks"]]
    assert titles == ["buy milk"]


# -------------------------------------------------------------- lifecycle


def test_stop_is_safe_without_start(tmp_path: Path) -> None:
    _, _, productivity = _app(tmp_path)

    asyncio.run(productivity.stop())


def test_scheduler_tick_without_signals_emits_nothing(tmp_path: Path) -> None:
    app = FastAPI()
    productivity = register(app, tmp_path / "p.db", clock=lambda: FIXED_NOW)
    productivity.store.add_habit("Stretch", time="08:00")

    assert asyncio.run(productivity.scheduler.tick()) == 0
