"""P05: GET /eink route, tested on a bare app with eink.register (main.py patch wires it in)."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.panels import eink
from app.panels.layouts import LayoutStore


class _Mac:
    def __init__(self) -> None:
        self.calendar_calls = 0

    def read_today_calendar(self):
        self.calendar_calls += 1
        return [{"start": "09:00", "title": "<b>Standup</b>", "all_day": False}]

    def get_weather(self, lat, lon, city):
        return {"ok": True, "city": city, "temperature_c": 21.4, "condition": "Clear"}


class _Store:
    def list_tasks(self):
        return [{"id": 1, "title": "Buy milk", "done": False}]

    def list_notes(self):
        return []


def _client(tmp_path):
    app = FastAPI()
    app.state.layouts = LayoutStore(tmp_path / "m.db")
    app.state.mac = _Mac()
    app.state.settings = SimpleNamespace(weather_latitude=0, weather_longitude=0, weather_city="Town")
    app.state.productivity = SimpleNamespace(store=_Store())
    eink.register(app)
    return app, TestClient(app)


def test_eink_page_renders_default_layout(tmp_path) -> None:
    app, client = _client(tmp_path)
    res = client.get("/eink")
    assert res.status_code == 200
    assert "no-store" in res.headers["cache-control"]
    assert 'http-equiv="refresh"' in res.text and "<script" not in res.text
    assert "/eink?" in res.text


def test_eink_unknown_layout_is_404(tmp_path) -> None:
    _, client = _client(tmp_path)
    assert client.get("/eink?layout=nope").status_code == 404


def test_eink_reads_only_the_sources_the_page_needs(tmp_path) -> None:
    app, client = _client(tmp_path)
    layout = app.state.layouts.create("Kindle", "starter")
    layout["pages"][0]["portrait"] = [
        {"id": "c", "type": "calendar", "x": 0, "y": 0, "w": 6, "h": 4, "config": {}},
        {"id": "t", "type": "tasks", "x": 0, "y": 4, "w": 6, "h": 4, "config": {}},
        {"id": "w", "type": "weather", "x": 0, "y": 8, "w": 6, "h": 2, "config": {}},
        {"id": "p", "type": "placeholder", "x": 0, "y": 10, "w": 6, "h": 2, "config": {}},
    ]
    app.state.layouts.save(layout["id"], layout)
    res = client.get(f"/eink?layout={layout['id']}&orientation=portrait&refresh=2")
    assert res.status_code == 200
    assert "&lt;b&gt;Standup" in res.text and "<b>Standup" not in res.text
    assert "Buy milk" in res.text and "21" in res.text
    assert 'content="120' in res.text
    assert res.text.count('class="w"') == 3
    assert app.state.mac.calendar_calls == 1


def test_eink_does_not_touch_the_calendar_without_a_calendar_widget(tmp_path) -> None:
    app, client = _client(tmp_path)
    client.get("/eink")
    assert app.state.mac.calendar_calls == 0
