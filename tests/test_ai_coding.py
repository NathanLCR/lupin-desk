"""Tests for AI coding (P09): sessions, quotas, GitHub, hook install/remove, permission prompts."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.actions import CURRENT_CALLER, ActionRegistry  # noqa: E402
from app.ai_coding import AiCoding, register  # noqa: E402
from app.ai_coding.github import GitHubWatcher, parse_remote  # noqa: E402
from app.ai_coding.hooks import HooksError, HooksInstaller  # noqa: E402
from app.ai_coding.permissions import PROMPTS_TOPIC, PermissionBroker, describe_tool  # noqa: E402
from app.ai_coding.quotas import build_quotas, forecast  # noqa: E402
from app.ai_coding.sessions import SessionReader  # noqa: E402
from app.device_hub import DeviceHub  # noqa: E402
from app.devices import DeviceStore  # noqa: E402

NOW = 1_800_000_000.0


def iso(ts: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def write_claude(root: Path, name: str, cwd: str, secret: str = "SECRET PROMPT TEXT") -> Path:
    folder = root / "-proj"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.jsonl"
    lines = [
        {"type": "user", "cwd": cwd, "timestamp": iso(NOW - 600), "message": {"content": secret}},
        {"type": "assistant", "timestamp": iso(NOW - 500), "message": {
            "id": "m1", "model": "claude-x", "usage": {"input_tokens": 10, "output_tokens": 5}}},
        # Same message id again (streaming): counted once, the last numbers win.
        {"type": "assistant", "timestamp": iso(NOW - 490), "message": {
            "id": "m1", "model": "claude-x", "usage": {
                "input_tokens": 10, "output_tokens": 20, "cache_read_input_tokens": 1000}}},
        {"type": "assistant", "timestamp": iso(NOW - 10), "message": {
            "id": "m2", "model": "claude-y", "usage": {"input_tokens": 1, "output_tokens": 2}}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines) + "\nnot json\n", encoding="utf-8")
    import os

    os.utime(path, (NOW - 10, NOW - 10))
    return path


def write_codex(root: Path, cwd: str, used: float = 40.0) -> Path:
    folder = root / "2026" / "11"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "rollout-abc.jsonl"
    lines = [
        {"type": "session_meta", "payload": {"id": "cx1", "cwd": cwd, "timestamp": iso(NOW - 3600)}},
        {"type": "turn_context", "payload": {"model": "gpt-x"}},
        {"type": "event_msg", "timestamp": iso(NOW - 1800), "payload": {
            "type": "token_count",
            "info": {"total_token_usage": {"total_tokens": 500, "cached_input_tokens": 100},
                     "last_token_usage": {"total_tokens": 500}},
            "rate_limits": {"primary": {
                "used_percent": used, "window_minutes": 600, "resets_at": NOW + 300 * 60}}}},
    ]
    path.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    import os

    os.utime(path, (NOW - 1800, NOW - 1800))
    return path


# --------------------------------------------------------------------------- sessions, quotas


def test_claude_session_summary_has_numbers_and_no_prompt_text(tmp_path):
    write_claude(tmp_path, "s1", "/Users/me/code/desk")
    sessions = SessionReader(tmp_path, None).read(NOW)
    assert len(sessions) == 1
    public = sessions[0].to_public(NOW)
    assert public["project"] == "desk"
    assert public["model"] == "claude-y"
    assert public["status"] == "active"
    assert public["tokens"] == 10 + 20 + 1 + 2
    assert public["cached_tokens"] == 1000
    assert public["duration_seconds"] == 590
    assert "SECRET" not in json.dumps(public)


def test_sessions_ignore_old_and_nested_files_and_missing_roots(tmp_path):
    import os

    old = write_claude(tmp_path, "old", "/a/b")
    os.utime(old, (NOW - 9 * 86400, NOW - 9 * 86400))
    nested = tmp_path / "-proj" / "s1" / "subagents"
    nested.mkdir(parents=True)
    (nested / "agent.jsonl").write_text("{}", encoding="utf-8")
    assert SessionReader(tmp_path, None).read(NOW) == []
    assert SessionReader(tmp_path / "missing", tmp_path / "missing2").read(NOW) == []


def test_codex_session_and_quota_forecast_from_real_rate_limit(tmp_path):
    write_codex(tmp_path, "/Users/me/code/other", used=40.0)
    sessions = SessionReader(None, tmp_path).read(NOW)
    assert sessions[0].tool == "codex" and sessions[0].model == "gpt-x"
    quotas = build_quotas(sessions, NOW)
    window = quotas["codex"]["limits"][0]
    assert window["used_percent"] == 40.0 and window["name"] == "primary"
    # 300 of 600 minutes elapsed at 40% -> projected 80% at reset, never exhausted.
    assert window["forecast"]["projected_percent_at_reset"] == 80.0
    assert window["forecast"]["exhausted_in_minutes"] is None
    assert quotas["codex"]["daily_tokens"][-1]["tokens"] == 500


def test_claude_never_gets_an_invented_limit(tmp_path):
    write_claude(tmp_path, "s1", "/a/b")
    quotas = build_quotas(SessionReader(tmp_path, None).read(NOW), NOW)
    assert quotas["claude"]["limits"] == []
    assert len(quotas["claude"]["daily_tokens"]) == 7
    assert sum(d["tokens"] for d in quotas["claude"]["daily_tokens"]) == 33


def test_forecast_projects_exhaustion_and_rejects_bad_windows():
    result = forecast(80.0, 600, NOW + 300 * 60, NOW)  # 80% after half the window
    assert result["exhausted_in_minutes"] == 75
    assert forecast(10.0, 600, NOW - 1, NOW) is None  # already reset
    assert forecast(10.0, 600, NOW + 9999 * 60, NOW) is None  # remaining longer than the window


def test_stale_codex_window_is_not_shown(tmp_path):
    write_codex(tmp_path, "/a/b")
    sessions = SessionReader(None, tmp_path).read(NOW)
    assert build_quotas(sessions, NOW + 10 * 3600)["codex"]["limits"] == []


# --------------------------------------------------------------------------- GitHub


class FakeRunner:
    def __init__(self, auth_ok=True, conclusion="failure", run_id=7):
        self.calls: list[list[str]] = []
        self.auth_ok = auth_ok
        self.conclusion = conclusion
        self.run_id = run_id

    def __call__(self, argv: list[str]):
        self.calls.append(argv)
        assert isinstance(argv, list)
        if argv[:2] == ["git", "-C"]:
            return 0, "git@github.com:me/desk.git\n"
        if argv[:3] == ["gh", "auth", "status"]:
            return (0 if self.auth_ok else 1), ""
        if argv[:3] == ["gh", "pr", "list"]:
            return 0, json.dumps([{"number": 3, "title": "Fix it", "url": "https://x/3"}])
        if argv[:3] == ["gh", "run", "list"]:
            return 0, json.dumps([{
                "databaseId": self.run_id, "status": "completed", "conclusion": self.conclusion,
                "name": "CI", "headBranch": "main", "url": "https://x/run", "createdAt": iso(NOW - 60)}])
        return 1, ""


def test_parse_remote_variants():
    assert parse_remote("git@github.com:me/desk.git") == "me/desk"
    assert parse_remote("https://github.com/me/desk") == "me/desk"
    assert parse_remote("https://gitlab.com/me/desk") is None


def test_github_reports_a_failing_run_once():
    runner = FakeRunner()
    watcher = GitHubWatcher(runner)
    first = watcher.poll(["/a", "/b"], NOW)
    assert first == [{"repo": "me/desk", "run_id": "7", "name": "CI"}]
    assert watcher.poll(["/a"], NOW + 300) == []
    runner.run_id = 8
    assert len(watcher.poll(["/a"], NOW + 600)) == 1
    state = watcher.state
    assert state["available"] and state["repos"][0]["reviews"][0]["number"] == 3
    assert len([c for c in runner.calls if c[:2] == ["git", "-C"]]) == 2  # remotes cached per folder


def test_github_not_logged_in_is_a_state_not_an_error():
    watcher = GitHubWatcher(FakeRunner(auth_ok=False))
    assert watcher.poll(["/a"], NOW) == []
    assert watcher.state == {"available": False, "repos": []}


def test_github_passing_run_emits_nothing():
    assert GitHubWatcher(FakeRunner(conclusion="success")).poll(["/a"], NOW) == []


# --------------------------------------------------------------------------- hooks install


ORIGINAL = '{\n    "model": "opus",\n  "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}\n}'


def make_installer(tmp_path, original: str | None = ORIGINAL):
    settings = tmp_path / "claude" / "settings.json"
    if original is not None:
        settings.parent.mkdir()
        settings.write_text(original, encoding="utf-8")
    return HooksInstaller(settings, tmp_path / "state.json", 8123), settings


def test_install_adds_three_hooks_and_keeps_the_users_own(tmp_path):
    installer, settings = make_installer(tmp_path)
    assert installer.status()["installed"] is False
    status = installer.install()
    assert status["installed"] is True
    data = json.loads(settings.read_text())
    assert data["model"] == "opus"
    assert set(data["hooks"]) == {"PermissionRequest", "Notification", "Stop"}
    assert len(data["hooks"]["Stop"]) == 2  # the user's own hook is still first
    assert data["hooks"]["Stop"][0]["hooks"][0]["command"] == "echo mine"
    command = data["hooks"]["PermissionRequest"][0]["hooks"][0]["command"]
    assert "127.0.0.1:8123/api/claude-hooks/permission" in command


def test_install_twice_changes_nothing(tmp_path):
    installer, settings = make_installer(tmp_path)
    installer.install()
    once = settings.read_bytes()
    installer.install()
    assert settings.read_bytes() == once


def test_remove_restores_the_original_file_byte_for_byte(tmp_path):
    installer, settings = make_installer(tmp_path)
    before = settings.read_bytes()
    installer.install()
    assert settings.read_bytes() != before
    assert installer.remove()["installed"] is False
    assert settings.read_bytes() == before
    assert not (tmp_path / "state.json").exists()


def test_remove_deletes_a_settings_file_we_created(tmp_path):
    installer, settings = make_installer(tmp_path, original=None)
    installer.install()
    assert settings.exists()
    installer.remove()
    assert not settings.exists()


def test_remove_after_the_user_edited_only_removes_our_entries(tmp_path):
    installer, settings = make_installer(tmp_path)
    installer.install()
    data = json.loads(settings.read_text())
    data["theme"] = "dark"
    settings.write_text(json.dumps(data), encoding="utf-8")
    installer.remove()
    after = json.loads(settings.read_text())
    assert after["theme"] == "dark" and after["model"] == "opus"
    assert after["hooks"] == {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}


def test_reinstall_after_the_user_edited_refuses_and_remove_then_install_works(tmp_path):
    installer, settings = make_installer(tmp_path)
    installer.install()
    data = json.loads(settings.read_text())
    data["theme"] = "dark"
    edited = json.dumps(data)
    settings.write_text(edited, encoding="utf-8")
    with pytest.raises(HooksError):
        installer.install()
    assert settings.read_text() == edited  # nothing was changed
    installer.remove()
    assert json.loads(settings.read_text())["theme"] == "dark"
    installer.install()
    installer.remove()
    assert json.loads(settings.read_text())["theme"] == "dark"  # never restores stale bytes


def test_backup_state_file_is_private(tmp_path):
    import stat

    installer, _ = make_installer(tmp_path)
    installer.install()
    assert stat.S_IMODE((tmp_path / "state.json").stat().st_mode) == 0o600


def test_command_parts_are_shell_quoted(tmp_path):
    import shlex

    installer, settings = make_installer(tmp_path)
    installer.install()
    command = json.loads(settings.read_text())["hooks"]["PermissionRequest"][0]["hooks"][0]["command"]
    assert shlex.split(command.removesuffix(" || true"))[0] == "curl"
    hostile = HooksInstaller(settings, tmp_path / "s2.json", 8123)._command("/x; rm -rf ~", 5)
    parts = shlex.split(hostile.removesuffix(" || true"))
    assert parts[-1].endswith("/x; rm -rf ~")  # one argv word, not a second command


def test_invalid_settings_are_never_touched(tmp_path):
    installer, settings = make_installer(tmp_path, original="{not json")
    with pytest.raises(HooksError):
        installer.install()
    assert settings.read_text() == "{not json"
    assert not (tmp_path / "state.json").exists()


def test_status_shows_exactly_what_would_be_added(tmp_path):
    installer, _ = make_installer(tmp_path)
    adds = installer.status()["adds"]
    assert set(adds) == {"PermissionRequest", "Notification", "Stop"}
    assert adds == installer.entries()


# --------------------------------------------------------------------------- permission broker


class FakeBus:
    def __init__(self):
        self.signals: list[Any] = []
        self.released: list[dict] = []

    async def emit(self, signal):
        self.signals.append(signal)

    async def release(self, **kwargs):
        self.released.append(kwargs)
        return 1


_device_counter = [0]


def make_entry(topics=(PROMPTS_TOPIC,), body="panel", roles=("panel",), device_id="auto"):
    sent: list[dict] = []

    async def send(message):
        sent.append(message)

    if device_id == "auto":
        _device_counter[0] += 1
        device_id = f"dev-{_device_counter[0]}"
    return {"send": send, "topics": set(topics), "body": body, "roles": list(roles),
            "device_id": device_id, "sent": sent}


def ack_all(broker, *entries):
    """What a rendered, visible prompt widget does: tell the server it shows each pending prompt."""
    for entry in entries:
        for prompt in broker.pending():
            broker.acknowledge(entry, prompt.id, True)


def make_broker(entries, bus=None, timeout=5.0, wall=lambda: 1000.0):
    hub = SimpleNamespace(entries=entries)
    bus = bus if bus is not None else FakeBus()
    return PermissionBroker(lambda: hub, lambda: bus, timeout=timeout, wall_clock=wall), bus


async def start_request(broker, tool_input=None):
    task = asyncio.create_task(
        broker.request("sess", "/Users/me/code/desk", "Bash", tool_input or {"command": "rm -rf build"})
    )
    await asyncio.sleep(0.01)
    return task


def test_allow_from_the_showing_panel_resolves_the_hook():
    async def run():
        panel = make_entry()
        broker, bus = make_broker([panel])
        task = await start_request(broker)
        prompt = broker.pending()[0]
        ack_all(broker, panel)
        shown = panel["sent"][-1]["data"]["prompts"][0]
        assert shown["tool"] == "Bash" and shown["args"] == "rm -rf build" and shown["project"] == "desk"
        assert broker.answer(panel, prompt.id, "allow") is True
        output = await task
        assert output["hookSpecificOutput"]["decision"]["behavior"] == "allow"
        assert broker.pending() == []
        assert bus.released == [{"id": prompt.id}]  # the held Expression is released
        # one-time: a second answer is rejected
        assert broker.answer(panel, prompt.id, "deny") is False

    asyncio.run(run())


def test_deny_returns_a_deny_decision():
    async def run():
        panel = make_entry()
        broker, _ = make_broker([panel])
        task = await start_request(broker)
        ack_all(broker, panel)
        assert broker.answer(panel, broker.pending()[0].id, "deny")
        assert (await task)["hookSpecificOutput"]["decision"]["behavior"] == "deny"

    asyncio.run(run())


def test_answer_from_a_device_not_showing_the_prompt_is_rejected():
    async def run():
        panel = make_entry()
        broker, _ = make_broker([panel])
        task = await start_request(broker)
        prompt = broker.pending()[0]
        stranger = make_entry()  # subscribed later, never shown this prompt
        broker._get_hub().entries.append(stranger)
        unsubscribed = make_entry(topics=())
        broker._get_hub().entries.append(unsubscribed)
        gone = make_entry()  # was shown, then disconnected
        ack_all(broker, panel, unsubscribed, gone)  # stranger never acks
        assert broker.answer(stranger, prompt.id, "allow") is False
        assert broker.answer(unsubscribed, prompt.id, "allow") is False
        assert broker.answer(gone, prompt.id, "allow") is False
        assert broker.answer(None, prompt.id, "allow") is False
        assert broker.answer(panel, "wrong-id", "allow") is False
        assert broker.answer(panel, prompt.id, "maybe") is False
        assert not task.done()
        assert broker.answer(panel, prompt.id, "allow")
        await task

    asyncio.run(run())


def test_prompts_only_go_to_registered_panels():
    async def run():
        panel = make_entry()
        editor = make_entry(body="editor", roles=[], device_id=None)
        legacy_body = make_entry(body="body", roles=["body"], device_id=None)
        body_device = make_entry(body="body", roles=["body"])
        anonymous_panel = make_entry(device_id=None)
        entries = [panel, editor, legacy_body, body_device, anonymous_panel]
        broker, _ = make_broker(entries)
        task = await start_request(broker)
        prompt = broker.pending()[0]
        assert panel["sent"]
        for other in entries[1:]:
            assert other["sent"] == []
            assert broker.acknowledge(other, prompt.id, True) is False
            assert broker.answer(other, prompt.id, "allow") is False
        ack_all(broker, panel)
        assert broker.answer(panel, prompt.id, "allow")
        await task

    asyncio.run(run())


def test_an_unacked_panel_cannot_allow():
    async def run():
        panel = make_entry()
        broker, _ = make_broker([panel])
        task = await start_request(broker)
        prompt = broker.pending()[0]
        assert panel["sent"]  # it received the prompt, but never said it shows it
        assert broker.answer(panel, prompt.id, "allow") is False
        assert not task.done()
        assert broker.acknowledge(panel, "wrong-id", True) is False
        assert broker.answer(panel, prompt.id, "allow") is False
        task.cancel()

    asyncio.run(run())


def test_a_hidden_page_cannot_allow_and_an_unsubscribe_drops_the_ack():
    async def run():
        panel = make_entry()
        broker, _ = make_broker([panel])
        task = await start_request(broker)
        prompt = broker.pending()[0]
        assert broker.acknowledge(panel, prompt.id, True) is True
        assert broker.acknowledge(panel, prompt.id, False) is False  # page hidden
        assert broker.answer(panel, prompt.id, "allow") is False
        assert broker.acknowledge(panel, prompt.id, "yes") is False  # only a real True counts
        assert broker.acknowledge(panel, prompt.id, True) is True
        panel["topics"].discard(PROMPTS_TOPIC)  # unsubscribed
        assert broker.answer(panel, prompt.id, "allow") is False
        panel["topics"].add(PROMPTS_TOPIC)  # re-subscribing does not revive the old ack
        assert broker.answer(panel, prompt.id, "allow") is False
        assert not task.done()
        task.cancel()

    asyncio.run(run())


def test_a_device_that_disconnected_cannot_answer():
    async def run():
        panel = make_entry()
        entries = [panel]
        broker, _ = make_broker(entries)
        task = await start_request(broker)
        ack_all(broker, panel)
        entries.remove(panel)
        assert broker.answer(panel, broker.pending()[0].id, "allow") is False
        task.cancel()

    asyncio.run(run())


def test_timeout_returns_no_decision_and_the_id_is_dead():
    async def run():
        panel = make_entry()
        broker, bus = make_broker([panel], timeout=0.05)
        task = await start_request(broker)
        prompt = broker.pending()[0]
        ack_all(broker, panel)
        assert await task == {}
        assert broker.answer(panel, prompt.id, "allow") is False
        assert bus.released

    asyncio.run(run())


def test_expired_prompt_is_rejected_even_before_the_timer_fires():
    async def run():
        panel = make_entry()
        now = [1000.0]
        broker, _ = make_broker([panel], timeout=60.0, wall=lambda: now[0])
        task = await start_request(broker)
        prompt = broker.pending()[0]
        ack_all(broker, panel)
        now[0] += 61
        assert broker.answer(panel, prompt.id, "allow") is False
        task.cancel()

    asyncio.run(run())


def test_no_panel_showing_means_no_prompt_and_claude_asks_itself():
    async def run():
        broker, bus = make_broker([make_entry(topics=())])
        assert await broker.request("s", "/x/y", "Bash", {"command": "ls"}) == {}
        assert broker.pending() == []
        assert len(bus.signals) == 1  # Lupin still says it once

    asyncio.run(run())


def test_prompt_content_never_reaches_signals_or_logs(caplog):
    async def run():
        panel = make_entry()
        broker, bus = make_broker([panel], timeout=0.05)
        with caplog.at_level("DEBUG"):
            await broker.request("s", "/x/desk", "Bash", {"command": "echo TOPSECRET-TOKEN"})
        blob = json.dumps([getattr(s, "data", {}) for s in bus.signals]) + repr(
            [getattr(s, "summary", "") for s in bus.signals]
        )
        assert "TOPSECRET" not in blob
        assert "TOPSECRET" not in caplog.text

    asyncio.run(run())


def test_needs_user_signal_is_important_and_asks_for_a_hold():
    async def run():
        panel = make_entry()
        broker, bus = make_broker([panel], timeout=0.05)
        await broker.request("s", "/x/desk", "Bash", {"command": "ls"})
        signal = bus.signals[0]
        assert signal.kind == "claude_code_needs_user" and signal.importance.name == "IMPORTANT"
        if hasattr(signal, "hold_expression"):  # present once p09-signals.py.diff is applied
            assert signal.hold_expression is True and signal.id

    asyncio.run(run())


def test_session_waiting_signals_and_releases():
    async def run():
        broker, bus = make_broker([])
        await broker.wait_for_user("abc")
        assert bus.signals[0].kind == "claude_code_needs_user"
        await broker.session_active("abc")
        assert bus.released == [{"id": "wait:abc"}]
        await broker.stop()

    asyncio.run(run())


def test_describe_tool_shows_the_full_command_or_arguments():
    assert describe_tool("Bash", {"command": "rm -rf build"}) == ("Bash", "rm -rf build")
    tool, args = describe_tool("Edit", {"old": "a", "new": "b"})
    assert tool == "Edit" and "old" in args
    assert len(describe_tool("Bash", {"command": "x" * 9000})[1]) == 4000


# --------------------------------------------------------------------------- actions + routes


def build_app(tmp_path, **kwargs):
    app = FastAPI()
    actions = ActionRegistry()
    hub = DeviceHub(DeviceStore(tmp_path / "d.db"), actions)
    app.state.actions = actions
    app.state.device_hub = hub
    service = register(
        app,
        port=8123,
        claude_root=tmp_path / "claude-root",
        codex_root=tmp_path / "codex-root",
        settings_path=tmp_path / "settings.json",
        state_path=tmp_path / "state.json",
        gh_runner=FakeRunner(),
        **kwargs,
    )
    return app, hub, service


def test_answer_action_uses_the_connection_that_sent_it(tmp_path):
    async def run():
        app, hub, service = build_app(tmp_path)
        panel, other = make_entry(), make_entry()
        hub.entries.extend([panel, other])
        task = asyncio.create_task(service.broker.request("s", "/a/desk", "Bash", {"command": "ls"}))
        await asyncio.sleep(0.01)
        prompt_id = service.broker.pending()[0].id
        replies = []

        async def send(message):
            replies.append(message)

        # A device that is not showing it (never published to it) is refused.
        hub.entries.append(stranger := make_entry())
        await hub.handle_message(stranger, {"type": "action", "id": "ai_coding_answer",
                                            "args": {"id": prompt_id, "decision": "allow"}}, send)
        assert replies[-1]["result"] == {"accepted": False}
        # A Panel that has not acked the prompt is refused too.
        await hub.handle_message(panel, {"type": "action", "id": "ai_coding_answer",
                                         "args": {"id": prompt_id, "decision": "allow"}}, send)
        assert replies[-1]["result"] == {"accepted": False}
        await hub.handle_message(panel, {"type": "action", "id": "ai_coding_prompt_shown",
                                         "args": {"id": prompt_id, "visible": True}}, send)
        assert replies[-1]["result"] == {"acked": True}
        await hub.handle_message(panel, {"type": "action", "id": "ai_coding_answer",
                                         "args": {"id": prompt_id, "decision": "allow"}}, send)
        assert replies[-1]["result"] == {"accepted": True}
        assert (await task)["hookSpecificOutput"]["decision"]["behavior"] == "allow"

    asyncio.run(run())


def test_a_disconnected_hook_caller_drops_the_prompt_and_releases_the_hold(tmp_path, monkeypatch):
    from app.ai_coding import routes

    monkeypatch.setattr(routes, "DISCONNECT_POLL_SECONDS", 0.01)

    class Gone:
        async def is_disconnected(self):
            return True

    async def run():
        app, hub, service = build_app(tmp_path)
        app.state.signals = bus = FakeBus()
        hub.entries.append(make_entry())
        work = service.broker.request("s", "/a/desk", "Bash", {"command": "ls"})
        assert await routes.run_until_disconnect(Gone(), work, {}) == {}
        assert service.broker.pending() == []
        assert len(bus.signals) == 1 and len(bus.released) == 1

    asyncio.run(run())


def test_caller_is_never_set_outside_a_connection():
    assert CURRENT_CALLER.get() is None


def mac_headers():
    return {"host": "127.0.0.1:8123", "content-type": "application/json"}


def test_hook_routes_install_and_remove_through_http(tmp_path, monkeypatch):
    monkeypatch.setattr("app.ai_coding.routes.is_macos", lambda: True)
    app, _hub, _service = build_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8123")
    sure = {"confirm": True}
    assert client.get("/api/claude-hooks").json()["installed"] is False
    assert client.post("/api/claude-hooks/install", headers=mac_headers(), json=sure).json()["installed"] is True
    assert (tmp_path / "settings.json").exists()
    assert client.post("/api/claude-hooks/remove", headers=mac_headers(), json=sure).json()["installed"] is False
    assert not (tmp_path / "settings.json").exists()


def test_install_and_remove_need_confirm_and_macos(tmp_path, monkeypatch):
    app, _hub, _service = build_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8123")
    monkeypatch.setattr("app.ai_coding.routes.is_macos", lambda: True)
    for path in ("install", "remove"):
        for body in (None, {}, {"confirm": "yes"}, {"confirm": False}):
            reply = client.post(f"/api/claude-hooks/{path}", headers=mac_headers(),
                                **({} if body is None else {"json": body}))
            assert reply.status_code == 400
    assert not (tmp_path / "settings.json").exists()
    monkeypatch.setattr("app.ai_coding.routes.is_macos", lambda: False)
    for path in ("install", "remove"):
        reply = client.post(f"/api/claude-hooks/{path}", headers=mac_headers(), json={"confirm": True})
        assert reply.status_code == 403
    assert not (tmp_path / "settings.json").exists()


def test_hook_routes_refuse_other_hosts_origins_and_content_types(tmp_path):
    app, _hub, _service = build_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8123")
    assert client.post("/api/claude-hooks/install", headers={**mac_headers(), "host": "evil.example"}).status_code == 403
    assert client.post("/api/claude-hooks/install", headers={**mac_headers(), "origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/claude-hooks/install", headers={"content-type": "text/plain"}).status_code == 415
    async def from_lan(scope, receive, send):
        if scope["type"] == "http":
            scope = {**scope, "client": ("192.168.1.9", 5000)}
        await app(scope, receive, send)

    lan = TestClient(from_lan, base_url="http://127.0.0.1:8123")
    assert lan.post("/api/claude-hooks/install", headers=mac_headers()).status_code == 403
    assert lan.post("/api/claude-hooks/permission", headers=mac_headers(), json={}).status_code == 403
    assert not (tmp_path / "settings.json").exists()


def test_permission_hook_falls_back_when_no_panel_is_showing(tmp_path):
    app, _hub, _service = build_app(tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8123")
    reply = client.post(
        "/api/claude-hooks/permission", headers=mac_headers(),
        json={"session_id": "s", "cwd": "/a/b", "tool_name": "Bash", "tool_input": {"command": "ls"}},
    )
    assert reply.status_code == 200 and reply.json() == {}


def test_only_real_prompts_make_lupin_speak_and_hold(tmp_path):
    app, _hub, _service = build_app(tmp_path)
    app.state.signals = bus = FakeBus()
    client = TestClient(app, base_url="http://127.0.0.1:8123")
    assert client.post("/api/claude-hooks/event", headers=mac_headers(),
                       json={"hook_event_name": "Stop", "session_id": "s"}).status_code == 200
    assert len(bus.signals) == 0  # Stop only updates the widget
    client.post("/api/claude-hooks/event", headers=mac_headers(),
                json={"hook_event_name": "Notification", "notification_type": "idle_prompt", "session_id": "s"})
    assert len(bus.signals) == 1
    # Notifications about auth etc. are not "needs the user".
    client.post("/api/claude-hooks/event", headers=mac_headers(),
                json={"hook_event_name": "Notification", "notification_type": "auth_success", "session_id": "s"})
    assert len(bus.signals) == 1


def test_snapshot_route_and_tick_publish_only_when_subscribed(tmp_path):
    write_claude(tmp_path / "claude-root", "s1", "/a/desk")
    app, hub, service = build_app(tmp_path)
    service._clock = lambda: NOW
    client = TestClient(app, base_url="http://127.0.0.1:8123")
    snap = client.get("/api/ai-coding/snapshot").json()
    assert snap["sessions"][0]["project"] == "desk"

    async def run():
        quiet = make_entry(topics=())
        hub.entries.append(quiet)
        await service.tick()
        assert quiet["sent"] == []
        watcher = make_entry(topics=("ai-coding",))
        hub.entries.append(watcher)
        await service.tick()
        topic_msgs = [m for m in watcher["sent"] if m.get("topic") == "ai-coding"]
        assert topic_msgs and topic_msgs[0]["data"]["sessions"][0]["project"] == "desk"

    asyncio.run(run())


def test_ci_failure_becomes_one_build_failed_signal(tmp_path):
    write_claude(tmp_path / "claude-root", "s1", "/a/desk")
    app, _hub, service = build_app(tmp_path, github_interval=0.0)
    service._clock = lambda: NOW
    app.state.signals = bus = FakeBus()

    async def run():
        await service.tick()
        await service.tick()

    asyncio.run(run())
    assert [s.kind for s in bus.signals] == ["build_failed"]
    assert bus.signals[0].data == {"repo": "me/desk", "workflow": "CI"}


def test_no_gh_call_at_boot_but_a_watching_panel_triggers_the_first_look(tmp_path):
    app, hub, service = build_app(tmp_path)
    runner = service.github._run
    service._clock = lambda: NOW

    async def run():
        service.start()
        await asyncio.sleep(0.05)  # the loop's first tick runs now
        await service.stop()
        assert runner.calls == []  # nothing at boot
        hub.entries.append(make_entry(topics=("ai-coding",)))
        await service.tick()
        assert any(call[:3] == ["gh", "auth", "status"] for call in runner.calls)

    asyncio.run(run())
