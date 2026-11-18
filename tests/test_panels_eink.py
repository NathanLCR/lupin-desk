"""Tests for the E-ink Panel renderer (app.panels.eink): widgets, pages, grid math, refresh and escaping."""

from __future__ import annotations

import copy
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.panels.eink import (
    EINK_WIDGET_TYPES,
    EinkData,
    clamp_refresh_minutes,
    render_page,
    render_widget,
    widget_types_on_page,
)
from app.panels.templates import build_from_template


NOW = datetime(2026, 11, 18, 9, 5)


def _data(**overrides: Any) -> EinkData:
    return EinkData(now=overrides.pop("now", NOW), **overrides)


def _widget(wid: str, wtype: str, x: int = 0, y: int = 0, w: int = 1, h: int = 1, config: Any = None) -> dict[str, Any]:
    return {"id": wid, "type": wtype, "x": x, "y": y, "w": w, "h": h, "config": config or {}}


def _layout(*, landscape: list[dict[str, Any]] | None = None, portrait: list[dict[str, Any]] | None = None,
            cols_l: int = 12, rows_l: int = 6, cols_p: int = 6, rows_p: int = 12) -> dict[str, Any]:
    return {
        "id": "t",
        "name": "T",
        "grid": {
            "landscape": {"cols": cols_l, "rows": rows_l},
            "portrait": {"cols": cols_p, "rows": rows_p},
        },
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "landscape": landscape or [],
                "portrait": portrait or [],
            }
        ],
    }


def test_clock_renders_time_and_am_with_hour12() -> None:
    html = render_widget(_widget("c", "clock"), _data())
    assert html is not None
    assert "09:05" in html

    html12 = render_widget(_widget("c", "clock", config={"hour12": True}), _data())
    assert html12 is not None
    assert "AM" in html12


def test_clock_date_line_has_day_and_month() -> None:
    html = render_widget(_widget("c", "clock"), _data())
    assert html is not None
    assert "18" in html
    assert "November" in html


def test_tasks_shows_only_open_tasks_and_escapes_titles() -> None:
    tasks = [
        {"id": "1", "title": "Buy milk", "done": False},
        {"id": "2", "title": "Finished thing", "done": True},
        {"id": "3", "title": "<script>alert(1)</script>", "done": False},
    ]
    html = render_widget(_widget("k", "tasks"), _data(tasks=tasks))
    assert html is not None
    assert "Buy milk" in html
    assert "Finished thing" not in html
    assert "<script" not in html.lower()
    assert "&lt;script&gt;" in html


def test_notes_are_escaped_and_truncated_at_160_chars() -> None:
    notes = [
        {"id": "n1", "text": "<b>bold</b>", "created_at": "2026-11-18T08:00:00"},
        {"id": "n2", "text": "x" * 300, "created_at": "2026-11-18T08:01:00"},
    ]
    html = render_widget(_widget("n", "notes"), _data(notes=notes))
    assert html is not None
    assert "<b>bold</b>" not in html
    assert "&lt;b&gt;bold&lt;/b&gt;" in html
    # The note is cut to 160 characters in total, ellipsis included: 157 kept + "...".
    assert "x" * 157 + "..." in html
    assert "x" * 158 not in html


def test_calendar_escapes_titles_and_handles_all_day_and_empty_states() -> None:
    events = [
        {"start": "10:00", "title": "<i>Standup</i>", "all_day": False},
        {"start": "00:00", "title": "Holiday", "all_day": True},
    ]
    html = render_widget(_widget("cal", "calendar"), _data(calendar=events))
    assert html is not None
    assert "&lt;i&gt;Standup&lt;/i&gt;" in html
    assert "<i>Standup</i>" not in html
    assert "All day" in html

    unavailable = render_widget(_widget("cal", "calendar"), _data(calendar=None))
    assert unavailable is not None
    assert "unavailable" in unavailable

    empty = render_widget(_widget("cal", "calendar"), _data(calendar=[]))
    assert empty is not None
    assert "No events" in empty


def test_weather_escapes_city_rounds_temperature_and_handles_failure() -> None:
    weather = {"ok": True, "city": "<img src=x>", "temperature_c": 20.6, "apparent_c": 19.2, "condition": "Sunny"}
    html = render_widget(_widget("w", "weather"), _data(weather=weather))
    assert html is not None
    assert "&lt;img src=x&gt;" in html
    assert "<img src=x>" not in html
    assert "21" in html

    failed = render_widget(_widget("w", "weather"), _data(weather={"ok": False, "city": "Lisbon",
                                                                   "temperature_c": None,
                                                                   "apparent_c": None,
                                                                   "condition": None}))
    assert failed is not None
    assert "unavailable" in failed


def test_today_escapes_headline_top_and_warnings_and_handles_none() -> None:
    today = {
        "headline": "<em>Focus</em> day",
        "top": [{"id": "t1", "why": "<b>urgent</b>"}],
        "warnings": ["<script>x</script>"],
    }
    html = render_widget(_widget("td", "today"), _data(today=today))
    assert html is not None
    assert "&lt;em&gt;Focus&lt;/em&gt; day" in html
    assert "&lt;b&gt;urgent&lt;/b&gt;" in html
    assert "<script" not in html.lower()

    empty = render_widget(_widget("td", "today"), _data(today=None))
    assert empty is not None
    assert "No summary" in empty


def test_lupin_line_prefers_config_text_and_escapes() -> None:
    widget = _widget("l", "lupin_line", config={"text": "Config <b>line</b>"})
    html = render_widget(widget, _data(lupin_line="Data line"))
    assert html is not None
    assert "Config &lt;b&gt;line&lt;/b&gt;" in html
    assert "Data line" not in html


def test_render_widget_returns_none_for_unknown_type() -> None:
    assert render_widget(_widget("p", "placeholder"), _data()) is None


def test_render_page_skips_unknown_widgets_and_stays_valid_html() -> None:
    layout = _layout(
        landscape=[
            _widget("c", "clock", x=0, y=0, w=4, h=2),
            _widget("p", "placeholder", x=4, y=0, w=4, h=2),
        ]
    )
    html = render_page(layout, page_id="home", orientation="landscape", data=_data())
    assert html.count('class="w"') == 1
    assert html.lstrip().lower().startswith("<!doctype html")
    assert "</html>" in html.lower()


def test_grid_size_comes_from_layout_grid() -> None:
    widget = _widget("c", "clock", x=2, y=0, w=2, h=1)

    four = _layout(landscape=[widget], cols_l=4, rows_l=4)
    html4 = render_page(four, page_id="home", orientation="landscape", data=_data())
    assert "left:50" in html4
    assert "width:50" in html4

    six = _layout(landscape=[widget], cols_l=6, rows_l=4)
    html6 = render_page(six, page_id="home", orientation="landscape", data=_data())
    assert "left:33.333" in html6
    assert html6 != html4


def test_layout_without_grid_falls_back_to_widget_extents() -> None:
    layout = {
        "id": "t",
        "name": "T",
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "landscape": [_widget("c", "clock", x=0, y=0, w=3, h=2)],
                "portrait": [],
            }
        ],
    }
    html = render_page(layout, page_id="home", orientation="landscape", data=_data())
    assert 'class="w"' in html


def test_refresh_meta_defaults_to_five_minutes_and_has_no_script() -> None:
    layout = build_from_template("starter")
    html = render_page(layout, page_id=layout["pages"][0]["id"], orientation="landscape", data=_data())
    assert "<script" not in html.lower()
    assert 'http-equiv="refresh"' in html
    assert 'content="300"' in html

    html1 = render_page(layout, page_id=layout["pages"][0]["id"], orientation="landscape",
                        data=_data(), refresh_minutes=1)
    assert 'content="60"' in html1


def test_refresh_url_is_escaped_in_meta() -> None:
    layout = build_from_template("starter")
    html = render_page(layout, page_id=layout["pages"][0]["id"], orientation="landscape",
                       data=_data(), refresh_url='https://example.test/x"y')
    assert "&quot;" in html
    assert 'x"y' not in html
    assert "300;url=" in html


def test_clamp_refresh_minutes() -> None:
    assert clamp_refresh_minutes(None) == 5
    assert clamp_refresh_minutes("abc") == 5
    assert clamp_refresh_minutes(0) == 1
    assert clamp_refresh_minutes(999) == 60
    assert clamp_refresh_minutes("10") == 10


def test_page_id_selects_second_page_and_unknown_falls_back_to_first() -> None:
    layout = _layout(landscape=[_widget("c", "clock")])
    layout["pages"] = [
        {"id": "first", "title": "First", "landscape": [_widget("n1", "notes")], "portrait": []},
        {"id": "second", "title": "Second", "landscape": [_widget("t1", "tasks")], "portrait": []},
    ]
    tasks = [{"id": "1", "title": "ONLY ON PAGE TWO", "done": False}]
    notes = [{"id": "n", "text": "ONLY ON PAGE ONE", "created_at": "2026-11-18T08:00:00"}]
    data = _data(tasks=tasks, notes=notes)

    second = render_page(layout, page_id="second", orientation="landscape", data=data)
    assert "ONLY ON PAGE TWO" in second
    assert "ONLY ON PAGE ONE" not in second

    fallback = render_page(layout, page_id="does-not-exist", orientation="landscape", data=data)
    assert "ONLY ON PAGE ONE" in fallback
    assert "ONLY ON PAGE TWO" not in fallback


def test_widget_types_on_page_returns_only_eink_types() -> None:
    assert EINK_WIDGET_TYPES == {
        "clock",
        "today",
        "calendar",
        "weather",
        "notes",
        "tasks",
        "checklist",
        "lupin_line",
    }
    page = {
        "id": "home",
        "title": "Home",
        "landscape": [
            _widget("c", "clock"),
            _widget("p", "placeholder"),
            _widget("k", "tasks"),
            _widget("cl", "checklist"),
        ],
        "portrait": [_widget("w", "weather")],
    }
    assert widget_types_on_page(page, "landscape") == {"clock", "tasks", "checklist"}
    assert widget_types_on_page(page, "portrait") == {"weather"}


def test_checklist_renders_open_tasks_and_corrupt_inputs_stay_safe() -> None:
    tasks = [{"id": "1", "title": "Call Alex", "done": False}]
    html = render_widget(_widget("cl", "checklist"), _data(tasks=tasks))
    assert html is not None
    assert "Call Alex" in html

    bad_cal = render_widget(_widget("cal", "calendar"), _data(calendar="corrupt"))
    assert bad_cal is not None and "unavailable" in bad_cal

    nan_weather = render_widget(
        _widget("w", "weather"),
        _data(weather={"ok": True, "city": "Lisbon", "temperature_c": float("nan"), "apparent_c": float("inf")}),
    )
    assert nan_weather is not None and "--" in nan_weather

    limited_cal = render_widget(
        _widget("cal", "calendar", config={"max": 1}),
        _data(calendar=[{"start": "09:00", "title": "First"}, {"start": "10:00", "title": "Second"}]),
    )
    assert limited_cal is not None and "First" in limited_cal and "Second" not in limited_cal
