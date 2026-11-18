"""Tests for Layouts (validation, merge, store) and their REST routes, including the arrange publish."""

from __future__ import annotations

import asyncio
import copy
import sys
from pathlib import Path
from typing import Any

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from app.config import BASE_DIR
from app.device_routes import setup_devices
from app.panels import routes as panel_routes
from app.panels.layouts import GRID, LayoutStore, merge_arrange, normalize_layout
from app.panels.templates import build_from_template, list_templates


def _require_testclient(request: Request) -> None:
    if request.client is None or request.client.host != "testclient":
        raise HTTPException(status_code=403, detail="Mac only.")


def _always_deny(request: Request) -> None:
    raise HTTPException(status_code=403, detail="Mac only.")


def _always_allow(request: Request) -> None:
    return None


def _starter() -> dict[str, Any]:
    return build_from_template("starter")


def _widget(wid: str = "w1", x: int = 0, y: int = 0, w: int = 2, h: int = 2, **extra: Any) -> dict[str, Any]:
    base = {"id": wid, "type": "clock", "x": x, "y": y, "w": w, "h": h, "config": {}}
    base.update(extra)
    return base


def _layout_with(landscape: list[dict[str, Any]] | None = None, portrait: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "name": "Test",
        "pages": [
            {"id": "home", "title": "Home", "landscape": landscape or [], "portrait": portrait or []},
        ],
    }


def _app(tmp_path: Path, require: Any = _require_testclient) -> FastAPI:
    app = FastAPI()
    setup_devices(app, tmp_path / "devices.db", require)
    panel_routes.register(app, tmp_path / "layouts.db", require)
    return app


def _connect_panel(app: FastAPI, device_id: str) -> list[dict[str, Any]]:
    """Open a fake Panel connection on the hub, subscribe to 'layout'; return its received messages."""
    hub = app.state.device_hub
    messages: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    body_info: dict[str, Any] = {}
    asyncio.run(hub.hello(body_info, {"body": "panel", "device_id": device_id, "protocol": 1}, send))
    entry = body_info["entry"]
    asyncio.run(hub.handle_message(entry, {"type": "subscribe", "topics": ["layout"]}, send))
    return messages


# ---------- normalize_layout ----------


def test_normalize_accepts_the_starter_template_and_adds_the_fixed_keys() -> None:
    clean = normalize_layout(_starter(), layout_id="starter")

    assert clean["id"] == "starter"
    assert clean["name"] == "Starter"
    assert clean["version"] == 1
    assert clean["grid"] == {"landscape": {"cols": 12, "rows": 6}, "portrait": {"cols": 6, "rows": 12}}
    [page] = clean["pages"]
    assert page["id"] == "home" and page["title"] == "Home"
    assert [w["id"] for w in page["landscape"]] == ["clock-1", "placeholder-1"]
    assert page["landscape"][1]["config"] == {"text": "Widget coming soon"}


def test_normalize_drops_unknown_keys_and_defaults_missing_lists_and_config() -> None:
    raw = {
        "name": "  Desk  ",
        "extra": "ignored",
        "pages": [{"id": "p1", "landscape": [{"id": "a", "type": "clock", "x": 0, "y": 0, "w": 1, "h": 1, "junk": 1}], "other": 2}],
    }

    clean = normalize_layout(raw, layout_id="desk-1")

    assert clean["name"] == "Desk"
    assert "extra" not in clean
    [page] = clean["pages"]
    assert set(page) == {"id", "title", "landscape", "portrait"}
    assert page["title"] == "p1"
    assert page["portrait"] == []
    assert page["landscape"] == [{"id": "a", "type": "clock", "x": 0, "y": 0, "w": 1, "h": 1, "config": {}}]


def test_normalize_allows_the_same_widget_id_in_both_orientations() -> None:
    raw = _layout_with(landscape=[_widget("same")], portrait=[_widget("same", w=6, h=6)])

    clean = normalize_layout(raw, layout_id="both")

    assert clean["pages"][0]["portrait"][0]["id"] == "same"


@pytest.mark.parametrize("bad_id", ["", "bad id", "x" * 33, "dot.id", "emoji-🙂"])
def test_normalize_rejects_bad_widget_ids(bad_id: str) -> None:
    with pytest.raises(ValueError, match="id"):
        normalize_layout(_layout_with(landscape=[_widget(bad_id)]), layout_id="ok-id")


def test_normalize_rejects_duplicate_widget_id_within_a_variant() -> None:
    raw = _layout_with(landscape=[_widget("dup"), _widget("dup", x=2)])

    with pytest.raises(ValueError, match="used twice"):
        normalize_layout(raw, layout_id="dup-layout")


def test_normalize_rejects_a_widget_outside_the_landscape_grid() -> None:
    raw = _layout_with(landscape=[_widget("far", x=10, w=4)])

    with pytest.raises(ValueError, match="landscape grid"):
        normalize_layout(raw, layout_id="far-layout")


def test_normalize_rejects_a_widget_outside_the_portrait_grid() -> None:
    raw = _layout_with(portrait=[_widget("tall", y=8, h=6)])

    with pytest.raises(ValueError, match="portrait grid"):
        normalize_layout(raw, layout_id="tall-layout")


def test_normalize_rejects_float_coordinates() -> None:
    raw = _layout_with(landscape=[_widget("f", x=1.5)])

    with pytest.raises(ValueError, match="whole number"):
        normalize_layout(raw, layout_id="float-layout")


def test_normalize_rejects_bool_coordinates() -> None:
    raw = _layout_with(landscape=[_widget("b", w=True)])

    with pytest.raises(ValueError, match="whole number"):
        normalize_layout(raw, layout_id="bool-layout")


def test_normalize_rejects_zero_size_and_negative_position() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        normalize_layout(_layout_with(landscape=[_widget("z", w=0)]), layout_id="zero-layout")
    with pytest.raises(ValueError, match="x and y"):
        normalize_layout(_layout_with(landscape=[_widget("n", x=-1)]), layout_id="neg-layout")


def test_normalize_rejects_an_oversize_config() -> None:
    raw = _layout_with(landscape=[_widget("big", config={"text": "a" * 9000})])

    with pytest.raises(ValueError, match="8192 bytes"):
        normalize_layout(raw, layout_id="big-layout")


def test_normalize_rejects_a_config_that_is_not_json() -> None:
    raw = _layout_with(landscape=[_widget("obj", config={"when": object()})])

    with pytest.raises(ValueError, match="plain JSON"):
        normalize_layout(raw, layout_id="obj-layout")


def test_normalize_rejects_zero_pages() -> None:
    with pytest.raises(ValueError, match="1 to 12 pages"):
        normalize_layout({"name": "Empty", "pages": []}, layout_id="empty-layout")


def test_normalize_rejects_thirteen_pages_and_accepts_twelve() -> None:
    pages = [{"id": f"p{i}", "title": "P"} for i in range(13)]
    with pytest.raises(ValueError, match="1 to 12 pages"):
        normalize_layout({"name": "Many", "pages": pages}, layout_id="many-layout")

    clean = normalize_layout({"name": "Twelve", "pages": pages[:12]}, layout_id="twelve-layout")
    assert len(clean["pages"]) == 12


def test_normalize_rejects_bad_and_duplicate_page_ids() -> None:
    with pytest.raises(ValueError, match="Page 1 id"):
        normalize_layout({"name": "Bad", "pages": [{"id": "no spaces"}]}, layout_id="bad-page")
    with pytest.raises(ValueError, match="used twice"):
        normalize_layout({"name": "Dup", "pages": [{"id": "a"}, {"id": "a"}]}, layout_id="dup-page")


def test_normalize_rejects_a_long_page_title_and_defaults_a_blank_one_to_the_id() -> None:
    with pytest.raises(ValueError, match="40 characters"):
        normalize_layout({"name": "T", "pages": [{"id": "a", "title": "x" * 41}]}, layout_id="title-layout")

    clean = normalize_layout({"name": "T", "pages": [{"id": "blank", "title": "   "}]}, layout_id="blank-title")
    assert clean["pages"][0]["title"] == "blank"


def test_normalize_rejects_too_many_widgets_on_one_variant() -> None:
    widgets = [_widget(f"w{i}", w=1, h=1, x=i % 12, y=i // 12) for i in range(37)]

    with pytest.raises(ValueError, match="more than 36"):
        normalize_layout(_layout_with(landscape=widgets), layout_id="crowded")


@pytest.mark.parametrize("name", ["", "   ", "x" * 61, 42])
def test_normalize_rejects_bad_names(name: Any) -> None:
    with pytest.raises(ValueError, match="name"):
        normalize_layout({"name": name, "pages": [{"id": "a"}]}, layout_id="name-layout")


def test_normalize_rejects_the_default_alias_and_bad_layout_ids() -> None:
    with pytest.raises(ValueError, match="Layout id"):
        normalize_layout(_starter(), layout_id="default")
    with pytest.raises(ValueError, match="Layout id"):
        normalize_layout(_starter(), layout_id="Bad Id")


def test_templates_list_and_build_return_independent_copies() -> None:
    assert list_templates() == [{"id": "starter", "name": "Starter"}]

    copied = build_from_template("starter")
    copied["pages"][0]["landscape"].clear()

    assert len(build_from_template("starter")["pages"][0]["landscape"]) == 2
    with pytest.raises(KeyError):
        build_from_template("nope")


# ---------- merge_arrange ----------


def test_merge_keeps_config_and_takes_the_new_position() -> None:
    layout = normalize_layout(_starter(), layout_id="starter")
    moved = [
        {"id": "placeholder-1", "type": "placeholder", "x": 0, "y": 0, "w": 4, "h": 6},
        {"id": "clock-1", "type": "clock", "x": 4, "y": 0, "w": 8, "h": 6},
    ]

    merged = merge_arrange(layout, "home", "landscape", moved)

    by_id = {w["id"]: w for w in merged["pages"][0]["landscape"]}
    assert (by_id["placeholder-1"]["x"], by_id["placeholder-1"]["w"]) == (0, 4)
    assert by_id["placeholder-1"]["config"] == {"text": "Widget coming soon"}
    assert by_id["clock-1"]["x"] == 4 and by_id["clock-1"]["config"] == {}


def test_merge_removes_missing_ids_and_adds_unknown_ids_with_empty_config() -> None:
    layout = normalize_layout(_starter(), layout_id="starter")
    body = [{"id": "fresh", "type": "clock", "x": 0, "y": 0, "w": 3, "h": 3}]

    merged = merge_arrange(layout, "home", "landscape", body)

    assert merged["pages"][0]["landscape"] == [
        {"id": "fresh", "type": "clock", "x": 0, "y": 0, "w": 3, "h": 3, "config": {}}
    ]


def test_merge_leaves_the_other_orientation_and_the_input_alone() -> None:
    layout = normalize_layout(_starter(), layout_id="starter")
    before = copy.deepcopy(layout)

    merged = merge_arrange(layout, "home", "portrait", [{"id": "clock-1", "type": "clock", "x": 0, "y": 0, "w": 6, "h": 6}])

    assert layout == before
    assert merged["pages"][0]["landscape"] == before["pages"][0]["landscape"]
    assert [w["id"] for w in merged["pages"][0]["portrait"]] == ["clock-1"]


def test_merge_rejects_out_of_bounds_and_bad_input() -> None:
    layout = normalize_layout(_starter(), layout_id="starter")

    with pytest.raises(ValueError, match="portrait grid"):
        merge_arrange(layout, "home", "portrait", [{"id": "a", "type": "clock", "x": 5, "y": 0, "w": 3, "h": 1}])
    with pytest.raises(ValueError):
        merge_arrange(layout, "home", "square", [])
    with pytest.raises(ValueError):
        merge_arrange(layout, "home", "landscape", [{"id": "a", "type": "clock", "x": 0.5, "y": 0, "w": 1, "h": 1}])
    with pytest.raises(ValueError):
        merge_arrange(layout, "home", "landscape", [{"id": "a", "type": "clock", "x": 0, "y": 0, "w": 1, "h": 1}] * 2)


def test_merge_unknown_page_raises_key_error() -> None:
    layout = normalize_layout(_starter(), layout_id="starter")

    with pytest.raises(KeyError):
        merge_arrange(layout, "missing", "landscape", [])


# ---------- LayoutStore ----------


def test_store_seeds_the_starter_layout_on_open(tmp_path: Path) -> None:
    store = LayoutStore(tmp_path / "layouts.db")

    try:
        assert [item["id"] for item in store.list()] == ["starter"]
        starter = store.get("starter")
        assert starter is not None and starter["name"] == "Starter"
        assert "updated_at" in starter
    finally:
        store.close()


def test_store_default_alias_resolves_to_starter(tmp_path: Path) -> None:
    store = LayoutStore(tmp_path / "layouts.db")

    try:
        assert store.get("default")["id"] == "starter"
        assert store.get("unknown") is None
    finally:
        store.close()


def test_create_from_template_uses_a_slug_with_six_hex_chars_and_the_given_name(tmp_path: Path) -> None:
    store = LayoutStore(tmp_path / "layouts.db")

    try:
        created = store.create("Desk Wide!")

        assert created["name"] == "Desk Wide!"
        assert created["id"].startswith("desk-wide-")
        suffix = created["id"].rsplit("-", 1)[1]
        assert len(suffix) == 6 and all(c in "0123456789abcdef" for c in suffix)
        assert created["pages"] == _starter()["pages"]
    finally:
        store.close()


def test_create_rejects_an_unknown_template(tmp_path: Path) -> None:
    store = LayoutStore(tmp_path / "layouts.db")

    try:
        with pytest.raises(ValueError, match="Unknown layout template"):
            store.create("Nope", "does-not-exist")
        assert len(store.list()) == 1
    finally:
        store.close()


def test_save_replaces_the_document_and_keeps_the_id(tmp_path: Path) -> None:
    store = LayoutStore(tmp_path / "layouts.db")

    try:
        created = store.create("Renamable")
        document = _layout_with(landscape=[_widget("solo", w=12, h=6)])
        document["id"] = "something-else"

        saved = store.save(created["id"], document)

        assert saved is not None
        assert saved["id"] == created["id"]
        assert saved["name"] == "Test"
        assert store.get(created["id"])["pages"][0]["landscape"][0]["id"] == "solo"
        assert store.save("missing-layout-000000", document) is None
    finally:
        store.close()


def test_delete_starter_is_blocked_and_custom_layouts_can_be_deleted(tmp_path: Path) -> None:
    store = LayoutStore(tmp_path / "layouts.db")

    try:
        with pytest.raises(ValueError, match="starter layout cannot be deleted"):
            store.delete("starter")
        with pytest.raises(ValueError):
            store.delete("default")

        created = store.create("Temp")
        assert store.delete(created["id"]) is True
        assert store.get(created["id"]) is None
        assert store.delete(created["id"]) is False
    finally:
        store.close()


def test_layouts_persist_across_reopen(tmp_path: Path) -> None:
    db_path = tmp_path / "layouts.db"
    first = LayoutStore(db_path)
    created = first.create("Kept")
    first.arrange(created["id"], "home", "landscape", [{"id": "clock-1", "type": "clock", "x": 1, "y": 1, "w": 4, "h": 2}])
    first.close()

    second = LayoutStore(db_path)
    try:
        kept = second.get(created["id"])
        assert kept is not None and kept["name"] == "Kept"
        assert kept["pages"][0]["landscape"][0]["x"] == 1
        assert [item["id"] for item in second.list()] == ["starter", created["id"]]
    finally:
        second.close()


def test_store_arrange_returns_none_for_unknown_layout(tmp_path: Path) -> None:
    store = LayoutStore(tmp_path / "layouts.db")

    try:
        assert store.arrange("missing-layout-000000", "home", "landscape", []) is None
        with pytest.raises(KeyError):
            store.arrange("starter", "missing", "landscape", [])
    finally:
        store.close()


# ---------- REST routes ----------


def test_list_get_default_and_templates(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))

    listing = client.get("/api/layouts")
    assert listing.status_code == 200
    assert [item["id"] for item in listing.json()["layouts"]] == ["starter"]
    assert set(listing.json()["layouts"][0]) == {"id", "name", "updated_at"}

    starter = client.get("/api/layouts/starter").json()
    assert client.get("/api/layouts/default").json() == starter
    assert starter["grid"]["portrait"] == {"cols": 6, "rows": 12}

    assert client.get("/api/layout-templates").json() == {"templates": [{"id": "starter", "name": "Starter"}]}


def test_get_unknown_layout_is_404(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))

    assert client.get("/api/layouts/nope-layout").status_code == 404


def test_create_save_and_delete_are_forbidden_off_the_mac(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, require=_always_deny))

    assert client.post("/api/layouts", json={"name": "Denied"}).status_code == 403
    assert client.put("/api/layouts/starter", json=_starter()).status_code == 403
    assert client.delete("/api/layouts/starter").status_code == 403
    assert client.get("/api/layouts").status_code == 200


def test_create_save_and_delete_work_on_the_mac(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, require=_always_allow))

    created = client.post("/api/layouts", json={"name": "Mac Made", "template": "starter"})
    assert created.status_code == 201
    layout_id = created.json()["id"]

    document = _layout_with(landscape=[_widget("only", w=6, h=3)])
    saved = client.put(f"/api/layouts/{layout_id}", json=document)
    assert saved.status_code == 200
    assert saved.json()["id"] == layout_id
    assert saved.json()["pages"][0]["landscape"][0]["id"] == "only"

    assert client.delete(f"/api/layouts/{layout_id}").json() == {"ok": True}
    assert client.get(f"/api/layouts/{layout_id}").status_code == 404


def test_deleting_the_starter_is_409_and_bad_saves_are_422(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, require=_always_allow))

    assert client.delete("/api/layouts/starter").status_code == 409
    assert client.put("/api/layouts/starter", json={"name": "Bad", "pages": []}).status_code == 422
    assert client.put("/api/layouts/unknown-layout", json=_starter()).status_code == 404
    assert client.post("/api/layouts", json={"name": "X", "template": "nope"}).status_code == 422


def test_arrange_from_a_non_mac_client_persists_and_keeps_config(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path, require=_always_deny))
    body = {
        "page_id": "home",
        "orientation": "landscape",
        "widgets": [
            {"id": "placeholder-1", "type": "placeholder", "x": 0, "y": 0, "w": 4, "h": 6},
            {"id": "clock-1", "type": "clock", "x": 4, "y": 0, "w": 8, "h": 6},
        ],
    }

    response = client.put("/api/layouts/starter/arrange", json=body)

    assert response.status_code == 200
    assert response.json()["pages"][0]["landscape"][0]["id"] == "placeholder-1"
    following = client.get("/api/layouts/starter").json()
    by_id = {w["id"]: w for w in following["pages"][0]["landscape"]}
    assert (by_id["clock-1"]["x"], by_id["clock-1"]["w"]) == (4, 8)
    assert by_id["placeholder-1"]["config"] == {"text": "Widget coming soon"}


def test_arrange_accepts_the_default_alias(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    body = {"page_id": "home", "orientation": "portrait", "widgets": [{"id": "clock-1", "type": "clock", "x": 0, "y": 0, "w": 6, "h": 4}]}

    response = client.put("/api/layouts/default/arrange", json=body)

    assert response.status_code == 200
    assert response.json()["id"] == "starter"


def test_arrange_unknown_layout_or_page_is_404_and_bad_input_is_422(tmp_path: Path) -> None:
    client = TestClient(_app(tmp_path))
    widgets = [{"id": "clock-1", "type": "clock", "x": 0, "y": 0, "w": 2, "h": 2}]

    assert client.put("/api/layouts/unknown-layout/arrange", json={"page_id": "home", "orientation": "landscape", "widgets": widgets}).status_code == 404
    assert client.put("/api/layouts/starter/arrange", json={"page_id": "nowhere", "orientation": "landscape", "widgets": widgets}).status_code == 404
    assert client.put("/api/layouts/starter/arrange", json={"page_id": "home", "orientation": "square", "widgets": widgets}).status_code == 422
    assert client.put("/api/layouts/starter/arrange", json={"page_id": "home", "orientation": "landscape", "widgets": [{"id": "a", "type": "clock", "x": 1.5, "y": 0, "w": 2, "h": 2}]}).status_code == 422
    assert client.put("/api/layouts/starter/arrange", json={"page_id": "home", "orientation": "landscape", "widgets": [{"id": "a", "type": "clock", "x": 11, "y": 0, "w": 2, "h": 2}]}).status_code == 422


def test_get_panel_serves_the_page_when_it_exists(tmp_path: Path) -> None:
    index_path = BASE_DIR / "static" / "panel" / "index.html"
    if not index_path.is_file():
        pytest.skip("static/panel/index.html is not there yet.")
    client = TestClient(_app(tmp_path))

    response = client.get("/panel")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_arrange_publishes_a_layout_topic_to_subscribed_devices(tmp_path: Path) -> None:
    app = _app(tmp_path, require=_always_deny)
    messages = _connect_panel(app, "panel-dev-0001")
    client = TestClient(app)
    body = {"page_id": "home", "orientation": "landscape", "widgets": [{"id": "clock-1", "type": "clock", "x": 0, "y": 0, "w": 4, "h": 4}]}

    response = client.put("/api/layouts/starter/arrange", json=body)

    assert response.status_code == 200
    assert {"type": "topic", "topic": "layout", "data": {"layout_id": "starter"}} in messages


def test_create_publishes_the_layout_topic_to_subscribed_devices(tmp_path: Path) -> None:
    app = _app(tmp_path, require=_always_allow)
    messages = _connect_panel(app, "panel-dev-0002")
    client = TestClient(app)

    created = client.post("/api/layouts", json={"name": "Announced"})

    assert created.status_code == 201
    assert {"type": "topic", "topic": "layout", "data": {"layout_id": created.json()["id"]}} in messages


def test_a_failing_publish_does_not_fail_the_arrange(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    app = _app(tmp_path, require=_always_deny)

    async def broken_publish(topic: str, payload: Any) -> int:
        raise RuntimeError("socket gone")

    app.state.device_hub.publish = broken_publish
    client = TestClient(app)
    body = {"page_id": "home", "orientation": "landscape", "widgets": [{"id": "clock-1", "type": "clock", "x": 0, "y": 0, "w": 4, "h": 4}]}

    with caplog.at_level("WARNING"):
        response = client.put("/api/layouts/starter/arrange", json=body)

    assert response.status_code == 200
    assert "socket gone" not in caplog.text
