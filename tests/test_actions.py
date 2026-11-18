"""Tests for the named-action registry in app/actions.py."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

from app.actions import ActionRegistry


def _run(registry: ActionRegistry, action_id: object, args: object) -> dict[str, Any]:
    return asyncio.run(registry.run(action_id, args))


def test_register_and_has() -> None:
    registry = ActionRegistry()
    registry.register("lights.on", lambda args: None, "Turn the lights on")

    assert registry.has("lights.on")
    assert not registry.has("lights.off")
    assert registry.list() == [{"id": "lights.on", "description": "Turn the lights on"}]


@pytest.mark.parametrize(
    "bad_id",
    ["", "Upper", "1starts-with-digit", "has space", "rm -rf /", "a" * 65, "trailing\n"],
)
def test_register_rejects_bad_id(bad_id: str) -> None:
    registry = ActionRegistry()
    with pytest.raises(ValueError):
        registry.register(bad_id, lambda args: None)


def test_register_rejects_duplicate() -> None:
    registry = ActionRegistry()
    registry.register("ping", lambda args: None)
    with pytest.raises(ValueError):
        registry.register("ping", lambda args: None)


def test_sync_handler_result_is_returned() -> None:
    registry = ActionRegistry()
    registry.register("add", lambda args: args["a"] + args["b"])

    reply = _run(registry, "add", {"a": 2, "b": 3})

    assert reply == {"type": "action_result", "id": "add", "ok": True, "result": 5}


def test_async_handler_result_is_awaited() -> None:
    registry = ActionRegistry()

    async def handler(args: dict[str, Any]) -> str:
        await asyncio.sleep(0)
        return f"hello {args['name']}"

    registry.register("greet", handler)

    reply = _run(registry, "greet", {"name": "desk"})

    assert reply == {
        "type": "action_result",
        "id": "greet",
        "ok": True,
        "result": "hello desk",
    }


def test_none_result_is_omitted() -> None:
    registry = ActionRegistry()
    registry.register("noop", lambda args: None)

    reply = _run(registry, "noop", {})

    assert reply == {"type": "action_result", "id": "noop", "ok": True}
    assert "result" not in reply


def test_none_args_are_treated_as_empty_dict() -> None:
    seen: list[dict[str, Any]] = []
    registry = ActionRegistry()
    registry.register("capture", lambda args: seen.append(args))

    reply = _run(registry, "capture", None)

    assert reply["ok"] is True
    assert seen == [{}]


def test_unknown_action_is_rejected_without_leaking_args(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = ActionRegistry()
    registry.register("ping", lambda args: "pong")

    with caplog.at_level(logging.WARNING, logger="app.actions"):
        reply = _run(registry, "nope", {"cmd": "rm -rf /"})

    assert reply == {
        "type": "action_result",
        "id": "nope",
        "ok": False,
        "error": "unknown_action",
    }
    assert "rm -rf" not in json.dumps(reply)
    assert "rm -rf" not in caplog.text
    assert "nope" in caplog.text


def test_non_str_id_is_rejected_with_none_id() -> None:
    registry = ActionRegistry()

    reply = _run(registry, 123, {})

    assert reply == {
        "type": "action_result",
        "id": None,
        "ok": False,
        "error": "unknown_action",
    }
    assert registry.has(123) is False


def test_invalid_args_are_rejected() -> None:
    registry = ActionRegistry()
    called: list[bool] = []
    registry.register("ping", lambda args: called.append(True))

    reply = _run(registry, "ping", ["not", "a", "dict"])

    assert reply == {
        "type": "action_result",
        "id": "ping",
        "ok": False,
        "error": "invalid_args",
    }
    assert called == []


def test_handler_exception_returns_action_failed_without_leaking_args(
    caplog: pytest.LogCaptureFixture,
) -> None:
    registry = ActionRegistry()

    def handler(args: dict[str, Any]) -> None:
        raise RuntimeError(f"boom with {args['secret']}")

    registry.register("explode", handler)

    with caplog.at_level(logging.ERROR, logger="app.actions"):
        reply = _run(registry, "explode", {"secret": "s3cr3t-token"})

    assert reply == {
        "type": "action_result",
        "id": "explode",
        "ok": False,
        "error": "action_failed",
    }
    assert "s3cr3t-token" not in json.dumps(reply)
    assert "s3cr3t-token" not in caplog.text
    assert "explode" in caplog.text


def test_async_handler_exception_returns_action_failed() -> None:
    registry = ActionRegistry()

    async def handler(args: dict[str, Any]) -> None:
        raise ValueError("bad")

    registry.register("explode_async", handler)

    reply = _run(registry, "explode_async", {})

    assert reply["ok"] is False
    assert reply["error"] == "action_failed"


def test_huge_id_is_truncated_in_reply(caplog: pytest.LogCaptureFixture) -> None:
    registry = ActionRegistry()
    huge_id = "a" * 200

    with caplog.at_level(logging.WARNING, logger="app.actions"):
        reply = _run(registry, huge_id, {})

    assert reply["ok"] is False
    assert reply["error"] == "unknown_action"
    assert reply["id"] == "a" * 64
    assert "a" * 65 not in caplog.text


def test_list_is_sorted_by_id() -> None:
    registry = ActionRegistry()
    registry.register("zeta", lambda args: None, "last")
    registry.register("alpha", lambda args: None, "first")
    registry.register("mid.dot:colon-dash_under", lambda args: None)

    assert [entry["id"] for entry in registry.list()] == [
        "alpha",
        "mid.dot:colon-dash_under",
        "zeta",
    ]
    assert registry.list()[0] == {"id": "alpha", "description": "first"}
