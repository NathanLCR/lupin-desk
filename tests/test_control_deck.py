"""Control Deck (P10): system audio, macros, webhooks, rules."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.actions import ActionRegistry
from app.control import register
from app.control.engine import GOTO_TOPIC, MacroRunner, RulesEngine
from app.control.store import ControlStore, validate_steps
from app.control.system import SystemControl, parse_volume_settings


class FakeHub:
    def __init__(self) -> None:
        self.published: list[tuple[str, Any]] = []

    async def publish(self, topic: str, payload: Any) -> int:
        self.published.append((topic, payload))
        return 1


class FakeMac:
    def __init__(self) -> None:
        self.commands: list[str] = []
        self.ran: list[dict[str, Any]] = []
        self.front = {"name": "Xcode", "title": "SECRET TITLE"}

    def execute_mac_command(self, name: str) -> dict[str, Any]:
        self.commands.append(name)
        return {"ok": True}

    def run_shortcut(self, shortcut: dict[str, Any]) -> dict[str, Any]:
        self.ran.append(shortcut)
        return {"ok": True}

    def validate_app_name(self, name: str) -> str | None:
        return name.strip() or None

    def activate_app(self, name: str) -> dict[str, Any]:
        self.ran.append({"activate": name})
        return {"ok": True}

    def front_app(self) -> dict[str, str] | None:
        return self.front


class FakeShortcuts:
    def __init__(self) -> None:
        self.items = {
            "ok_one": {"slug": "ok_one", "action_type": "keystroke", "requires_confirmation": False},
            "locked": {"slug": "locked", "action_type": "mac_command", "requires_confirmation": True},
            "ask": {"slug": "ask", "action_type": "agent_prompt", "requires_confirmation": False},
        }

    def get_shortcut(self, ident: str) -> dict[str, Any] | None:
        return self.items.get(ident)


class FakeBus:
    def __init__(self) -> None:
        self.emitted: list[Any] = []
        self.listeners: list[Any] = []

    async def emit(self, signal: Any) -> None:
        self.emitted.append(signal)
        for cb in list(self.listeners):
            await cb(signal)

    def add_listener(self, cb: Any) -> Any:
        self.listeners.append(cb)
        return lambda: self.listeners.remove(cb)


@pytest.fixture
def ctx(tmp_path: Path):
    app = FastAPI()
    app.state.actions = ActionRegistry()
    for media in ("media.play_pause", "media.next", "media.previous"):  # registered by app/panels/everyday.py
        app.state.actions.register(media, lambda args, media=media: {"ran": media})
    app.state.device_hub = hub = FakeHub()
    app.state.mac = mac = FakeMac()
    app.state.shortcuts = FakeShortcuts()
    app.state.signals = bus = FakeBus()
    flags = {"mac": True}

    def require_mac_client(request, detail="x"):
        if not flags["mac"]:
            raise HTTPException(status_code=403, detail=detail)

    deck = register(app, tmp_path / "c.db", require_mac_client)
    client = TestClient(app, headers={"host": "127.0.0.1:8000", "content-type": "application/json"})
    return SimpleNamespace(app=app, hub=hub, mac=mac, bus=bus, flags=flags, deck=deck, client=client)


def run(ctx, action: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    return asyncio.run(ctx.app.state.actions.run(action, args))


# ---------------------------------------------------------------- system audio


def test_parse_volume_settings():
    parsed = parse_volume_settings("output volume:50, input volume:0, alert volume:100, output muted:true")
    assert parsed == {"volume": 50, "muted": True, "mic_level": 0}


def test_mic_toggle_mutes_then_restores():
    calls: list[list[str]] = []
    level = {"v": 60}

    def runner(argv, **kw):
        calls.append(argv)
        script = argv[2]
        if script == "get volume settings":
            out = f"output volume:30, input volume:{level['v']}, output muted:false"
            return SimpleNamespace(returncode=0, stdout=out)
        level["v"] = int(script.rsplit(" ", 1)[1])
        return SimpleNamespace(returncode=0, stdout="")

    system = SystemControl(FakeMac(), run=runner)
    assert system.mic_toggle()["mic_muted"] is True
    assert level["v"] == 0
    assert system.mic_toggle()["mic_muted"] is False
    assert level["v"] == 60
    assert all(isinstance(a, list) and a[0] == "/usr/bin/osascript" for a in calls)


def test_volume_and_media_actions_use_whitelisted_commands(ctx):
    for action in ("volume.up", "volume.down", "volume.mute"):
        assert run(ctx, action)["ok"] is True
    assert ctx.mac.commands == ["volume_up", "volume_down", "volume_mute"]


# ---------------------------------------------------------------------- macros


def test_macro_validation():
    good = [{"action": "volume.up", "delay_ms": 100}, {"action": "shortcut.run", "args": {"slug": "ok_one"}}]
    assert len(validate_steps(good)) == 2
    for bad in (
        [],
        [{"action": "volume.up"}] * 11,
        [{"action": "tasks.remove"}],
        [{"action": "macro.run"}],
        [{"action": "volume.up", "delay_ms": 5000}],
        [{"action": "shortcut.run", "args": {"slug": "../x"}}],
        [{"action": "volume.up", "delay_ms": 2000}] * 6,
        ["volume.up"],
    ):
        with pytest.raises(ValueError):
            validate_steps(bad)


def test_macro_runs_steps_in_order_with_delays(ctx):
    sleeps: list[float] = []

    async def fake_sleep(s: float) -> None:
        sleeps.append(s)

    ctx.deck.runner._sleep = fake_sleep
    macro = ctx.deck.store.add_macro("Focus", [
        {"action": "volume.mute", "delay_ms": 500},
        {"action": "media.play_pause"},
        {"action": "shortcut.run", "args": {"slug": "ok_one"}},
    ])
    reply = run(ctx, "macro.run", {"id": macro["id"]})
    assert reply["ok"] and reply["result"] == {"id": macro["id"], "ok": True, "ran": 3}
    assert ctx.mac.commands == ["volume_mute"]
    assert ctx.mac.ran == [ctx.app.state.shortcuts.items["ok_one"]]
    assert sleeps == [0.5]


def test_macro_stops_at_a_failing_step_and_refuses_gated_shortcuts(ctx):
    macro = ctx.deck.store.add_macro("m", [
        {"action": "volume.up"},
        {"action": "shortcut.run", "args": {"slug": "locked"}},
        {"action": "volume.down"},
    ])
    reply = run(ctx, "macro.run", {"id": macro["id"]})
    assert reply["result"] == {"id": macro["id"], "ok": False, "ran": 1}
    assert ctx.mac.commands == ["volume_up"]
    assert run(ctx, "shortcut.run", {"slug": "ask"})["ok"] is False
    assert run(ctx, "macro.run", {"id": 999})["ok"] is False


def test_macro_runner_rechecks_the_whitelist_at_run_time(tmp_path):
    store = ControlStore(tmp_path / "m.db")
    macro = store.add_macro("m", [{"action": "volume.up"}])
    store._conn.execute(
        "UPDATE control_macros SET steps = ? WHERE id = ?",
        ('[{"action": "tasks.remove", "args": {}, "delay_ms": 0}]', macro["id"]),
    )
    registry = ActionRegistry()
    registry.register("tasks.remove", lambda a: 1 / 0)
    result = asyncio.run(MacroRunner(store, registry).run(macro["id"]))
    assert result["ok"] is False and result["ran"] == 0


def test_macro_routes_are_mac_only(ctx):
    body = {"name": "A", "steps": [{"action": "volume.up"}]}
    assert ctx.client.post("/api/control/macros", json=body).status_code == 200
    assert ctx.client.get("/api/control/macros").json()["macros"][0]["name"] == "A"
    bad = ctx.client.post("/api/control/macros", json={"name": "B", "steps": [{"action": "rm"}]})
    assert bad.status_code == 400
    ctx.flags["mac"] = False
    assert ctx.client.post("/api/control/macros", json=body).status_code == 403
    assert ctx.client.delete("/api/control/macros/1").status_code == 403
    assert ctx.client.get("/api/control/macros").status_code == 200


# -------------------------------------------------------------------- webhooks


def test_webhook_updates_widget_and_emits_signal(ctx):
    hook = ctx.client.post("/api/control/webhooks", json={"name": "Door"}).json()["webhook"]
    assert hook["path"].startswith("/hooks/") and len(hook["path"]) > 30
    lan = TestClient(ctx.app)  # a LAN device: no token, no loopback Host
    response = lan.post(hook["path"], json={"value": 42})
    assert response.status_code == 200
    topic, payload = ctx.hub.published[-1]
    assert topic == "webhooks" and payload["value"] == "42" and payload["id"] == hook["id"]
    signal = ctx.bus.emitted[-1]
    assert signal.kind == f"webhook.{hook['id']}"
    assert "42" not in str(signal.data) and signal.summary == ""
    assert ctx.client.get("/api/control/webhooks").json()["webhooks"][0]["value"] == "42"


def test_webhook_secrets_stay_on_the_mac_and_unknown_paths_404(ctx, caplog):
    hook = ctx.client.post("/api/control/webhooks", json={"name": "Door"}).json()["webhook"]
    secret = hook["path"].rsplit("/", 1)[1]
    ctx.flags["mac"] = False
    listed = ctx.client.get("/api/control/webhooks").json()["webhooks"][0]
    assert "path" not in listed and secret not in str(listed)
    assert ctx.client.post("/api/control/webhooks", json={"name": "x"}).status_code == 403
    assert ctx.client.post(f"/api/control/webhooks/{hook['id']}/rotate").status_code == 403
    with caplog.at_level(logging.DEBUG):
        assert TestClient(ctx.app).post("/hooks/not-a-real-secret", json={}).status_code == 404
        TestClient(ctx.app).post(hook["path"], json={"value": "x"})
    app_logs = "\n".join(r.getMessage() for r in caplog.records if r.name.startswith("app"))
    assert secret not in app_logs and "not-a-real-secret" not in app_logs


@pytest.mark.skipif(
    "/hooks/" not in "".join(p.pattern for p, _ in __import__("app.config", fromlist=["x"])._SECRET_PATTERNS),
    reason="needs .scratch/agents/patches/p10-app-config.py.diff (access log redaction)",
)
def test_access_log_redacts_webhook_paths():
    from app.config import SecretRedactingFilter

    assert "abc123" not in SecretRedactingFilter().redact("POST /hooks/abc123_-X HTTP/1.1")


def test_webhook_rotate_invalidates_the_old_path(ctx):
    hook = ctx.client.post("/api/control/webhooks", json={"name": "Door"}).json()["webhook"]
    new = ctx.client.post(f"/api/control/webhooks/{hook['id']}/rotate").json()["webhook"]
    assert new["path"] != hook["path"]
    assert TestClient(ctx.app).post(hook["path"], json={}).status_code == 404
    assert TestClient(ctx.app).post(new["path"], json={}).status_code == 200


def test_webhook_rejects_big_bodies_bad_json_and_floods(ctx):
    hook = ctx.client.post("/api/control/webhooks", json={"name": "Door"}).json()["webhook"]
    lan = TestClient(ctx.app)
    assert lan.post(hook["path"], content=b"x" * 5000).status_code == 413
    assert lan.post(hook["path"], content=b"{nope").status_code == 400
    assert lan.post(hook["path"], json={"value": "y" * 1000}).status_code == 200
    assert len(ctx.hub.published[-1][1]["value"]) == 200
    codes = [lan.post(hook["path"], json={"value": 1}).status_code for _ in range(70)]
    assert 429 in codes


# ----------------------------------------------------------------------- rules


def test_rule_validation_and_mac_only(ctx):
    ok = ctx.client.post("/api/control/rules", json={"trigger": "app_front", "match": "Xcode", "page_id": "p1"})
    assert ok.status_code == 200
    for body in (
        {"trigger": "app_front", "match": "", "page_id": "p1"},
        {"trigger": "shell", "match": "x", "page_id": "p1"},
        {"trigger": "signal", "match": "Bad Kind!", "page_id": "p1"},
        {"trigger": "signal", "match": "timer_done", "page_id": "../x"},
    ):
        assert ctx.client.post("/api/control/rules", json=body).status_code == 400
    ctx.flags["mac"] = False
    assert ctx.client.get("/api/control/rules").status_code == 403
    body = {"trigger": "signal", "match": "a", "page_id": "p"}
    assert ctx.client.post("/api/control/rules", json=body).status_code == 403


async def _ticks(engine: RulesEngine, n: int) -> int:
    return sum([1 for _ in range(n) if await engine.tick()])


def test_app_rule_switches_once_per_change_and_keeps_no_name(ctx, caplog):
    ctx.deck.store.add_rule("app_front", "xcode", "dev")
    with caplog.at_level(logging.DEBUG):
        assert asyncio.run(_ticks(ctx.deck.rules, 3)) == 1
    assert ctx.hub.published == [(GOTO_TOPIC, {"page_id": "dev"})]
    assert "Xcode" not in caplog.text and "SECRET TITLE" not in caplog.text
    assert "xcode" not in repr(vars(ctx.deck.rules)).lower()
    ctx.mac.front = {"name": "Safari", "title": ""}
    asyncio.run(ctx.deck.rules.tick())
    ctx.mac.front = {"name": "Xcode", "title": ""}
    assert asyncio.run(ctx.deck.rules.tick()) is True


def test_front_app_is_not_read_without_an_enabled_rule(ctx):
    reads: list[int] = []
    ctx.deck.rules._front_app = lambda: reads.append(1) or {"name": "Xcode"}
    assert asyncio.run(ctx.deck.rules.tick()) is False
    rule = ctx.deck.store.add_rule("app_front", "Xcode", "dev")
    ctx.deck.store.set_rule_enabled(rule["id"], False)
    assert asyncio.run(ctx.deck.rules.tick()) is False
    assert reads == []


def test_signal_rule_switches_page(ctx):
    ctx.deck.store.add_rule("signal", "timer_done", "home")
    ctx.deck.store.add_rule("signal", "build_failed", "ci")
    asyncio.run(ctx.deck.rules.on_signal(SimpleNamespace(kind="timer_done")))
    assert ctx.hub.published == [(GOTO_TOPIC, {"page_id": "home"})]


def test_start_subscribes_to_signals_and_stop_unsubscribes(ctx):
    async def go() -> None:
        ctx.deck.start()
        assert len(ctx.bus.listeners) == 1
        await ctx.deck.stop()
        assert ctx.bus.listeners == []

    asyncio.run(go())
