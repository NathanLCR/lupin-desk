"""Tests for LAN/SSRF security, WS confirmations and the lazy factory of `app.main`."""

from __future__ import annotations

import asyncio
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings, resolve_runtime_access_token
from app.main import create_app


class _FakeMac:
    """MacController mock to test confirmations and resize without touching macOS."""

    def __init__(self) -> None:
        self.activated_apps: list[str] = []

    def activate_app(self, app_name: str) -> dict[str, Any]:
        self.activated_apps.append(app_name)
        return {"ok": True, "app": app_name}

    def list_running_apps(self) -> list[str]:
        return []


class _FakeLLM:
    """LLMClient mock that emits the configured action tags per turn."""

    async def stream_chat(self, **kwargs: Any):
        yield {"type": "emotion", "emotion": "curious"}
        yield {"type": "action", "kind": "app", "target": "Safari"}
        yield {"type": "delta", "text": "Vou abrir o Safari."}
        yield {"type": "sentence", "text": "Vou abrir o Safari."}
        yield {"type": "done"}


def _make_settings(tmp_path: Path, **overrides: Any) -> Settings:
    defaults: dict[str, Any] = {
        "db_path": tmp_path / "test.db",
        "cowork_workspace_path": tmp_path / "missing-cowork",
        "host": "0.0.0.0",
        "desk_access_token": "lan-secret-123",
        "llm_api_key": "sk-super-secret-1234",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def test_resolve_runtime_access_token_behavior(tmp_path: Path) -> None:
    s_loopback = _make_settings(tmp_path, host="127.0.0.1", desk_access_token="")
    tok_lb, gen_lb = resolve_runtime_access_token(s_loopback)
    assert tok_lb == ""
    assert gen_lb is False

    s_lan = _make_settings(tmp_path, host="0.0.0.0", desk_access_token="")
    tok_lan, gen_lan = resolve_runtime_access_token(s_lan)
    assert len(tok_lan) >= 12
    assert gen_lan is True

    s_fixed = _make_settings(tmp_path, host="0.0.0.0", desk_access_token="my-pin")
    tok_fixed, gen_fixed = resolve_runtime_access_token(s_fixed)
    assert tok_fixed == "my-pin"
    assert gen_fixed is False


def test_dev_no_token_mode_opens_lan_even_with_configured_token(tmp_path: Path) -> None:
    s_dev = _make_settings(tmp_path, desk_access_token="my-pin", desk_dev_no_token=True)
    assert resolve_runtime_access_token(s_dev) == ("", False)

    app = create_app(settings=s_dev)

    async def lan_asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        patched = dict(scope)
        patched["client"] = ("192.168.1.50", 54321)
        await app(patched, receive, send)

    with TestClient(lan_asgi) as lan_client:
        assert lan_client.get("/api/skills").status_code == 200
        with lan_client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "interrupt"})
            assert ws.receive_json()["type"] == "interrupted"


def test_dev_no_token_mode_only_turns_on_with_explicit_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import load_settings

    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.delenv("DESK_DEV_SEM_TOKEN", raising=False)
    for value, expected in (("1", True), ("true", True), ("sim", True), ("0", False), ("", False)):
        monkeypatch.setenv("DESK_DEV_NO_TOKEN", value)
        assert load_settings(empty_env).desk_dev_no_token is expected, value
    monkeypatch.delenv("DESK_DEV_NO_TOKEN")
    assert load_settings(empty_env).desk_dev_no_token is False


def test_dev_no_token_mode_honours_legacy_env_var_as_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import load_settings

    empty_env = tmp_path / ".env"
    empty_env.write_text("", encoding="utf-8")
    monkeypatch.delenv("DESK_DEV_NO_TOKEN", raising=False)
    monkeypatch.setenv("DESK_DEV_SEM_TOKEN", "1")
    assert load_settings(empty_env).desk_dev_no_token is True
    # The new name wins whenever it is set, even against the legacy one.
    monkeypatch.setenv("DESK_DEV_NO_TOKEN", "0")
    assert load_settings(empty_env).desk_dev_no_token is False


def test_import_app_main_has_no_db_side_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_PATH", str(tmp_path / "must_not_exist.db"))
    sys.modules.pop("app.main", None)
    importlib.import_module("app.main")
    assert not (tmp_path / "must_not_exist.db").exists()


def test_lan_auth_http_and_ws(tmp_path: Path) -> None:
    app = create_app(settings=_make_settings(tmp_path))

    # Loopback (TestClient default) passes without a token
    with TestClient(app) as local_client:
        assert local_client.get("/api/skills").status_code == 200
        # Graceful degradation without Cowork
        st = local_client.get("/api/cowork/state").json()
        assert st["cowork_available"] is False

    # A non-loopback client (via an ASGI wrapper simulating a LAN IP) needs a Bearer token on /api/* and /ws
    async def lan_asgi(scope: dict[str, Any], receive: Any, send: Any) -> None:
        patched = dict(scope)
        patched["client"] = ("192.168.1.50", 54321)
        await app(patched, receive, send)

    with TestClient(lan_asgi) as lan_client:
        assert lan_client.get("/health").status_code == 200
        assert lan_client.get("/api/skills").status_code == 401
        ok_resp = lan_client.get(
            "/api/skills",
            headers={"Authorization": "Bearer lan-secret-123"},
        )
        assert ok_resp.status_code == 200

        with pytest.raises(WebSocketDisconnect) as exc_info:
            with lan_client.websocket_connect("/ws"):
                pass
        assert exc_info.value.code == 4401

        with lan_client.websocket_connect("/ws?token=lan-secret-123") as ws:
            ws.send_json({"type": "interrupt"})
            assert ws.receive_json()["type"] == "interrupted"


def test_llm_models_ssrf_guard(tmp_path: Path) -> None:
    app = create_app(settings=_make_settings(tmp_path))
    with TestClient(app) as client:
        resp = client.get(
            "/api/llm/models",
            params={"provider_id": "openai", "base_url": "https://evil.example/v1"},
        )
        assert resp.status_code == 400


def test_ws_app_requires_confirmation(tmp_path: Path) -> None:
    fake_mac = _FakeMac()
    fake_llm = _FakeLLM()
    app = create_app(
        settings=_make_settings(tmp_path),
        mac_controller=fake_mac,  # type: ignore[arg-type]
        llm_client=fake_llm,  # type: ignore[arg-type]
    )

    with TestClient(app) as client:
        with client.websocket_connect("/ws") as ws:
            ws.send_json({"type": "text", "text": "abra o Safari"})

            approval: dict[str, Any] | None = None
            for _ in range(15):
                msg = ws.receive_json()
                if msg.get("type") == "tool_approval_request":
                    approval = msg
                    break

            assert approval is not None
            assert approval["kind"] == "mac_app"
            assert fake_mac.activated_apps == []
            app_req = approval

            def recv_action_executed() -> dict[str, Any]:
                for _ in range(15):
                    m = ws.receive_json()
                    if m.get("type") == "action_executed":
                        return m
                raise AssertionError("action_executed not received")

            # Declining mac_app -> does not open the app
            ws.send_json({"type": "confirm_action", "approval_id": app_req["approval_id"], "approved": False})
            app_cancelled = recv_action_executed()
            assert app_cancelled["type"] == "action_executed"
            assert app_cancelled["ok"] is False
            assert app_cancelled["cancelled"] is True
            assert fake_mac.activated_apps == []
