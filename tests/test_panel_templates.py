"""Built-in Layout templates: shape, validity and store creation."""

from __future__ import annotations

from typing import Any

import pytest

from app.panels.layouts import GRID, LayoutStore, normalize_layout
from app.panels.templates import build_from_template, list_templates

EXPECTED_IDS = ["starter", "home", "system", "ai-coding", "music", "planner", "control-deck"]


def _rect(widget: dict[str, Any]) -> tuple[int, int, int, int]:
    return widget["x"], widget["y"], widget["x"] + widget["w"], widget["y"] + widget["h"]


def _overlaps(a: dict[str, Any], b: dict[str, Any]) -> bool:
    ax0, ay0, ax1, ay1 = _rect(a)
    bx0, by0, bx1, by1 = _rect(b)
    return ax0 < bx1 and bx0 < ax1 and ay0 < by1 and by0 < ay1


def test_template_list_is_starter_then_the_new_templates_in_order() -> None:
    assert list_templates() == [
        {"id": "starter", "name": "Starter"},
        {"id": "home", "name": "Home"},
        {"id": "system", "name": "System"},
        {"id": "ai-coding", "name": "AI coding"},
        {"id": "music", "name": "Music"},
        {"id": "planner", "name": "Planner"},
        {"id": "control-deck", "name": "Control Deck"},
    ]


@pytest.mark.parametrize("template_id", EXPECTED_IDS)
def test_every_template_normalizes_as_a_layout(template_id: str) -> None:
    layout = normalize_layout(build_from_template(template_id), layout_id="x-1")

    assert layout["id"] == "x-1"
    assert layout["version"] == 1
    assert layout["grid"] == {"landscape": {"cols": 12, "rows": 6}, "portrait": {"cols": 6, "rows": 12}}
    assert len(layout["pages"]) == 1


@pytest.mark.parametrize("template_id", EXPECTED_IDS)
def test_every_template_has_unique_widgets_inside_the_grid_without_overlaps(template_id: str) -> None:
    template = build_from_template(template_id)
    for orientation, (cols, rows) in GRID.items():
        widgets = template["pages"][0][orientation]
        ids = [widget["id"] for widget in widgets]
        assert len(ids) == len(set(ids)), f"{template_id} {orientation} repeats a widget id"
        assert 1 <= len(widgets) <= 4
        for widget in widgets:
            assert widget["x"] >= 0 and widget["y"] >= 0
            assert widget["w"] >= 1 and widget["h"] >= 1
            assert widget["x"] + widget["w"] <= cols, f"{template_id} {orientation} {widget['id']} exceeds cols"
            assert widget["y"] + widget["h"] <= rows, f"{template_id} {orientation} {widget['id']} exceeds rows"
            assert widget["type"] in {"clock", "placeholder"}
        for index, first in enumerate(widgets):
            for second in widgets[index + 1 :]:
                assert not _overlaps(first, second), f"{template_id} {orientation}: {first['id']} overlaps {second['id']}"


def test_home_has_a_clock_and_two_or_three_placeholders() -> None:
    widgets = build_from_template("home")["pages"][0]["landscape"]
    types = [widget["type"] for widget in widgets]

    assert types.count("clock") == 1
    assert 2 <= types.count("placeholder") <= 3


@pytest.mark.parametrize("template_id", EXPECTED_IDS)
def test_store_creates_a_layout_from_each_template(template_id: str) -> None:
    store = LayoutStore(":memory:")
    try:
        created = store.create("My", template_id)

        assert created["name"] == "My"
        assert created["pages"] == build_from_template(template_id)["pages"]
        assert store.get(created["id"]) is not None
    finally:
        store.close()
