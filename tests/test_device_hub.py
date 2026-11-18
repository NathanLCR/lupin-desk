"""Unit tests for `DeviceHub`: Active Body selection, hello/welcome, roles, topics and actions."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.actions import ActionRegistry
from app.device_hub import DeviceHub
from app.devices import DeviceStore


def _hub(tmp_path: Path, actions: ActionRegistry | None = None) -> DeviceHub:
    return DeviceHub(DeviceStore(tmp_path / "devices.db"), actions or ActionRegistry())


def _sink() -> tuple[list[dict[str, Any]], Any]:
    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    return messages, send


def _connect(hub: DeviceHub, data: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Open a fake connection with a hello; return its entry and every message it received."""
    messages, send = _sink()
    body_info: dict[str, Any] = {}
    asyncio.run(hub.hello(body_info, data, send))
    return body_info["entry"], messages


def test_legacy_hello_welcome_fields_and_audio_flag(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    entry, messages = _connect(hub, {"body": "esp32", "audio": ["pcm16"]})

    assert messages == [
        {"type": "welcome", "protocol": 1, "active_body": "esp32", "active": True}
    ]
    assert entry["wants_audio"] is True
    assert hub.current_active_body() is entry


def test_kind_rank_esp32_beats_rg406h_beats_web(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    _, _ = _connect(hub, {"body": "web"})
    rg, _ = _connect(hub, {"body": "rg406h-web"})
    assert hub.current_active_body() is rg

    esp, _ = _connect(hub, {"body": "esp32"})
    assert hub.current_active_body() is esp

    _connect(hub, {"body": "web"})
    assert hub.current_active_body() is esp


def test_latest_hello_wins_within_the_same_kind(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    first, first_messages = _connect(hub, {"body": "rg406h-web"})
    second, second_messages = _connect(hub, {"body": "rg406h-web"})

    assert hub.current_active_body() is second
    assert second_messages[0]["active"] is True
    assert first_messages[-1] == {"type": "active_body", "active_body": "rg406h-web", "active": False}


def test_active_body_notices_on_arrival_and_fails_over_on_disconnect(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    rg, rg_messages = _connect(hub, {"body": "rg406h-web"})
    esp, _ = _connect(hub, {"body": "esp32"})

    assert rg_messages[-1] == {"type": "active_body", "active_body": "esp32", "active": False}

    asyncio.run(hub.disconnect(esp))

    assert rg_messages[-1] == {"type": "active_body", "active_body": "rg406h-web", "active": True}
    assert hub.current_active_body() is rg


def test_first_time_device_id_hello_creates_panel_only_device(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    _, messages = _connect(
        hub,
        {"body": "panel", "device_id": "panel-0001-aaaa", "name": "Moto G5", "screen": {"w": 360}},
    )

    assert messages == [
        {
            "type": "welcome",
            "protocol": 1,
            "active_body": None,
            "active": False,
            "device_id": "panel-0001-aaaa",
            "name": "Moto G5",
            "roles": ["panel"],
            "layout_id": None,
        }
    ]
    assert hub.store.get("panel-0001-aaaa")["roles"] == ["panel"]


def test_a_panel_never_becomes_the_active_body(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    _, panel_messages = _connect(hub, {"body": "panel", "device_id": "panel-0002-bbbb"})
    assert hub.current_active_body() is None

    body, _ = _connect(hub, {"body": "rg406h-web"})

    assert hub.current_active_body() is body
    assert panel_messages[-1] == {"type": "active_body", "active_body": "rg406h-web", "active": False}


def test_setting_body_role_in_store_then_device_changed_activates_device(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    entry, messages = _connect(hub, {"body": "panel", "device_id": "panel-0003-cccc", "name": "Desk"})

    hub.store.update("panel-0003-cccc", roles=["body"])
    asyncio.run(hub.device_changed("panel-0003-cccc"))

    role_messages = [m for m in messages if m["type"] == "role"]
    assert role_messages == [
        {
            "type": "role",
            "device_id": "panel-0003-cccc",
            "name": "Desk",
            "roles": ["body"],
            "layout_id": None,
            "active": True,
        }
    ]
    assert hub.current_active_body() is entry
    assert messages[-1] == {"type": "active_body", "active_body": "panel", "active": True}


def test_user_priority_beats_kind_rank(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    hub.store.upsert_hello("rg-device-0001", name="RG", kind="rg406h-web")
    hub.store.update("rg-device-0001", roles=["body"])
    hub.store.set_body_priority_order(["rg-device-0001"])

    _, esp_messages = _connect(hub, {"body": "esp32"})
    rg, rg_messages = _connect(hub, {"body": "rg406h-web", "device_id": "rg-device-0001"})

    assert hub.current_active_body() is rg
    assert rg_messages[0]["active"] is True
    assert esp_messages[-1] == {"type": "active_body", "active_body": "rg406h-web", "active": False}


def test_two_ranked_bodies_only_highest_is_active_and_disconnect_moves_it(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    hub.store.upsert_hello("body-aaaa-0001", name="A", kind="rg406h-web")
    hub.store.upsert_hello("body-bbbb-0002", name="B", kind="rg406h-web")
    hub.store.update("body-aaaa-0001", roles=["body"])
    hub.store.update("body-bbbb-0002", roles=["body"])
    hub.store.set_body_priority_order(["body-aaaa-0001", "body-bbbb-0002"])

    b_entry, b_messages = _connect(hub, {"body": "rg406h-web", "device_id": "body-bbbb-0002"})
    a_entry, a_messages = _connect(hub, {"body": "rg406h-web", "device_id": "body-aaaa-0001"})

    assert hub.current_active_body() is a_entry
    assert a_messages[0]["active"] is True
    assert b_messages[-1] == {"type": "active_body", "active_body": "rg406h-web", "active": False}

    asyncio.run(hub.disconnect(a_entry))

    assert hub.current_active_body() is b_entry
    assert b_messages[-1] == {"type": "active_body", "active_body": "rg406h-web", "active": True}


def test_removing_last_body_role_sends_active_body_none(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    hub.store.upsert_hello("body-cccc-0003", name="C", kind="esp32")
    hub.store.update("body-cccc-0003", roles=["body"])
    _, body_messages = _connect(hub, {"body": "esp32", "device_id": "body-cccc-0003"})
    _, panel_messages = _connect(hub, {"body": "panel", "device_id": "panel-dddd-0004"})

    hub.store.update("body-cccc-0003", roles=["panel"])
    asyncio.run(hub.device_changed("body-cccc-0003"))

    assert hub.current_active_body() is None
    assert panel_messages[-1] == {"type": "active_body", "active_body": None, "active": False}
    assert body_messages[-1] == {"type": "active_body", "active_body": None, "active": False}


def test_subscribe_filters_topics_and_publish_reaches_only_subscribers(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    entry, messages = _connect(hub, {"body": "esp32"})
    send = entry["send"]

    asyncio.run(
        hub.handle_message(
            entry,
            {"type": "subscribe", "topics": ["sensor.temp", "BAD TOPIC", "Upper", "ok_1", 5, "x" * 65]},
            send,
        )
    )
    assert messages[-1] == {"type": "subscribed", "topics": ["ok_1", "sensor.temp"]}

    assert asyncio.run(hub.publish("sensor.temp", {"celsius": 21})) == 1
    assert messages[-1] == {"type": "topic", "topic": "sensor.temp", "data": {"celsius": 21}}
    assert asyncio.run(hub.publish("other.topic", {})) == 0

    asyncio.run(hub.handle_message(entry, {"type": "unsubscribe", "topics": ["sensor.temp"]}, send))
    assert messages[-1] == {"type": "subscribed", "topics": ["ok_1"]}
    assert asyncio.run(hub.publish("sensor.temp", {})) == 0


def test_subscribe_with_non_list_topics_is_an_error(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    entry, messages = _connect(hub, {"body": "esp32"})

    asyncio.run(hub.handle_message(entry, {"type": "subscribe", "topics": "sensor.temp"}, entry["send"]))

    assert messages[-1] == {"type": "error", "message": "topics must be a list."}


def test_subscription_set_is_capped_at_64_topics(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    entry, messages = _connect(hub, {"body": "esp32"})
    topics = [f"topic-{index:02d}" for index in range(70)]

    asyncio.run(hub.handle_message(entry, {"type": "subscribe", "topics": topics}, entry["send"]))

    assert len(messages[-1]["topics"]) == 64
    assert len(entry["topics"]) == 64


def test_subscribe_before_hello_is_an_error(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    messages, send = _sink()

    handled = asyncio.run(hub.handle_message(None, {"type": "subscribe", "topics": ["a1"]}, send))

    assert handled is True
    assert messages == [{"type": "error", "message": "Send hello first."}]


def test_unhandled_message_type_returns_false(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    messages, send = _sink()

    handled = asyncio.run(hub.handle_message(None, {"type": "typing", "active": True}, send))

    assert handled is False
    assert messages == []


def test_action_unknown_id_fails_and_registered_handler_runs(tmp_path: Path) -> None:
    actions = ActionRegistry()
    calls: list[dict[str, Any]] = []

    def ping(args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return {"pong": True}

    actions.register("device.ping", ping, "Ping the device")
    hub = _hub(tmp_path, actions)
    entry, messages = _connect(hub, {"body": "esp32"})

    asyncio.run(hub.handle_message(entry, {"type": "action", "id": "nope.missing", "args": {}}, entry["send"]))
    assert messages[-1] == {
        "type": "action_result",
        "id": "nope.missing",
        "ok": False,
        "error": "unknown_action",
    }

    asyncio.run(hub.handle_message(entry, {"type": "action", "id": "device.ping", "args": {"x": 1}}, entry["send"]))
    assert messages[-1] == {
        "type": "action_result",
        "id": "device.ping",
        "ok": True,
        "result": {"pong": True},
    }
    assert calls == [{"x": 1}]


def test_raw_legacy_entries_do_not_crash_hub_logic(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    legacy_messages: list[dict[str, Any]] = []

    async def legacy_send(message: dict[str, Any]) -> None:
        legacy_messages.append(message)

    legacy = {"body": "esp32", "seq": 999, "send": legacy_send, "wants_audio": True}
    hub.entries.append(legacy)

    assert hub.current_active_body() is legacy

    entry, messages = _connect(hub, {"body": "rg406h-web"})

    assert hub.current_active_body() is legacy
    assert messages[0]["active"] is False
    assert legacy_messages == []  # the Active Body did not change, so nobody is notified
    asyncio.run(hub.device_changed())
    assert asyncio.run(hub.publish("any.topic", {})) == 0
    assert entry in hub.entries


def test_legacy_body_kind_is_stored_as_body_and_panel_once(tmp_path: Path) -> None:
    from app.device_hub import DeviceHub
    from app.devices import DeviceStore
    from app.actions import ActionRegistry

    store = DeviceStore(tmp_path / "d.db")
    hub = DeviceHub(store, ActionRegistry())
    sent: list[dict] = []

    async def send(msg: dict) -> None:
        sent.append(msg)

    async def go() -> None:
        info: dict = {}
        await hub.hello(info, {"body": "rg406h-web", "device_id": "dev-rg406h01"}, send)
        assert sent[-1]["roles"] == ["body", "panel"] and sent[-1]["active"] is True
        info2: dict = {}
        await hub.hello(info2, {"body": "kindle", "device_id": "dev-kindle01"}, send)
        assert sent[-1]["roles"] == ["panel"]
        # A stored role is never overwritten on reconnect.
        store.update("dev-rg406h01", roles=["panel"])
        await hub.disconnect(info["entry"])
        info3: dict = {}
        await hub.hello(info3, {"body": "rg406h-web", "device_id": "dev-rg406h01"}, send)
        assert sent[-1]["roles"] == ["panel"] and sent[-1]["active"] is False

    asyncio.run(go())


def test_editor_preview_hello_is_ephemeral_and_never_steals_active_body(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    body_entry, body_msgs = _connect(hub, {"body": "web", "device_id": "dev-macweb01"})
    assert body_msgs[0]["active"] is True

    # Even if an editor client mistakenly sends the Mac's device_id, it must not touch DeviceStore or Active Body.
    ed_entry, ed_msgs = _connect(hub, {"body": "editor", "device_id": "dev-macweb01", "name": "Layout editor"})
    assert ed_msgs[0]["active"] is False
    assert ed_msgs[0]["active_body"] == "web"
    assert ed_entry["roles"] == []
    assert ed_entry["device_id"] is None
    assert hub.current_active_body() is body_entry
    assert hub.store.get("dev-macweb01")["kind"] == "web"
    assert len(body_msgs) == 1  # Mac window did not receive an active_body=False takeover

    asyncio.run(hub.handle_message(ed_entry, {"type": "subscribe", "topics": ["timers"]}, ed_entry["send"]))
    assert asyncio.run(hub.publish("timers", {"timers": []})) == 1
    assert ed_msgs[-1] == {"type": "topic", "topic": "timers", "data": {"timers": []}}
