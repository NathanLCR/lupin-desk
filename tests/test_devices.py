"""Unit tests for the connected devices store (`DeviceStore`)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.devices import DeviceStore


def test_first_hello_creates_panel_only_default(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        record = store.upsert_hello("abcd1234efgh", name="  Kitchen Panel  ", kind="panel", screen={"w": 960, "h": 720})
        assert record["id"] == "abcd1234efgh"
        assert record["name"] == "Kitchen Panel"
        assert record["roles"] == ["panel"]
        assert record["layout_id"] is None
        assert record["body_priority"] is None
        assert record["screen"] == {"w": 960, "h": 720}
        assert record["kind"] == "panel"
        assert record["created_at"]
        assert record["last_seen"]
    finally:
        store.close()


def test_hello_without_name_gets_fallback_name(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        record = store.upsert_hello("abcd1234efgh")
        assert record["name"] == "Device abcd"
        assert record["screen"] == {}
    finally:
        store.close()


def test_second_hello_keeps_stored_name_and_roles(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        store.upsert_hello("abcd1234efgh", name="Original")
        store.update("abcd1234efgh", roles=["body", "panel"])
        record = store.upsert_hello("abcd1234efgh", name="Different", kind="body-v2", screen={"w": 1})
        assert record["name"] == "Original"
        assert record["roles"] == ["body", "panel"]
        assert record["kind"] == "body-v2"
        assert record["screen"] == {"w": 1}
    finally:
        store.close()


def test_oversized_or_invalid_screen_is_dropped(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        record = store.upsert_hello("abcd1234efgh", screen={"blob": "x" * 2000})
        assert record["screen"] == {}
        record = store.upsert_hello("abcd1234efgh", screen=["not", "a", "dict"])  # type: ignore[arg-type]
        assert record["screen"] == {}
    finally:
        store.close()


def test_kind_and_name_are_truncated(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        record = store.upsert_hello("abcd1234efgh", name="n" * 100, kind="k" * 100)
        assert len(record["name"]) == 60
        assert len(record["kind"]) == 40
    finally:
        store.close()


def test_invalid_device_id_raises(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        for bad in ("short", "has space 123", "bad/slash_1234", "x" * 65, "", None):
            with pytest.raises(ValueError):
                store.upsert_hello(bad)  # type: ignore[arg-type]
    finally:
        store.close()


def test_update_roles_are_deduped_and_ordered(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        store.upsert_hello("abcd1234efgh")
        record = store.update("abcd1234efgh", roles=["panel", "body"])
        assert record is not None
        assert record["roles"] == ["body", "panel"]
        record = store.update("abcd1234efgh", roles=["panel", "panel"])
        assert record is not None
        assert record["roles"] == ["panel"]
    finally:
        store.close()


def test_update_validation_errors(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        store.upsert_hello("abcd1234efgh")
        bad_calls = [
            {"name": ""},
            {"name": "   "},
            {"name": 42},
            {"roles": []},
            {"roles": "body"},
            {"roles": ["wall"]},
            {"roles": ["body", 1]},
            {"layout_id": "x" * 65},
            {"layout_id": 7},
            {"body_priority": -1},
            {"body_priority": True},
            {"body_priority": "1"},
        ]
        for kwargs in bad_calls:
            with pytest.raises(ValueError):
                store.update("abcd1234efgh", **kwargs)
    finally:
        store.close()


def test_explicit_none_clears_and_omitted_keeps(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        store.upsert_hello("abcd1234efgh")
        record = store.update("abcd1234efgh", layout_id="living-room", body_priority=3)
        assert record is not None
        assert record["layout_id"] == "living-room"
        assert record["body_priority"] == 3

        record = store.update("abcd1234efgh", name="Renamed")
        assert record is not None
        assert record["layout_id"] == "living-room"
        assert record["body_priority"] == 3
        assert record["name"] == "Renamed"

        record = store.update("abcd1234efgh", layout_id=None, body_priority=None)
        assert record is not None
        assert record["layout_id"] is None
        assert record["body_priority"] is None
    finally:
        store.close()


def test_unknown_device_update_returns_none(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        assert store.update("nosuchdevice1", name="Ghost") is None
        assert store.get("nosuchdevice1") is None
    finally:
        store.close()


def test_set_body_priority_order(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        store.upsert_hello("device_aaaa1")
        store.upsert_hello("device_bbbb2")
        store.upsert_hello("device_cccc3")
        store.update("device_aaaa1", body_priority=9)

        store.set_body_priority_order(["device_cccc3", "unknown_id_99", "device_aaaa1"])

        assert store.get("device_cccc3")["body_priority"] == 0  # type: ignore[index]
        assert store.get("device_aaaa1")["body_priority"] == 1  # type: ignore[index]
        assert store.get("device_bbbb2")["body_priority"] is None  # type: ignore[index]
        assert store.get("unknown_id_99") is None
    finally:
        store.close()


def test_list_orders_most_recently_seen_first(tmp_path: Path) -> None:
    store = DeviceStore(db_path=tmp_path / "devices.db")
    try:
        store.upsert_hello("device_aaaa1")
        store.upsert_hello("device_bbbb2")
        store.upsert_hello("device_cccc3")
        assert [d["id"] for d in store.list()] == ["device_cccc3", "device_bbbb2", "device_aaaa1"]

        store.touch("device_aaaa1")
        assert [d["id"] for d in store.list()][0] == "device_aaaa1"
    finally:
        store.close()


def test_data_persists_after_reopening(tmp_path: Path) -> None:
    db_file = tmp_path / "devices.db"
    store = DeviceStore(db_path=db_file)
    store.upsert_hello("abcd1234efgh", name="Desk")
    store.update("abcd1234efgh", roles=["body"], layout_id="desk-a", body_priority=0)
    store.close()

    reopened = DeviceStore(db_path=db_file)
    try:
        record = reopened.get("abcd1234efgh")
        assert record is not None
        assert record["name"] == "Desk"
        assert record["roles"] == ["body"]
        assert record["layout_id"] == "desk-a"
        assert record["body_priority"] == 0
    finally:
        reopened.close()


def test_memory_database_works(tmp_path: Path) -> None:
    store = DeviceStore(db_path=":memory:")
    try:
        store.upsert_hello("abcd1234efgh")
        assert len(store.list()) == 1
    finally:
        store.close()
