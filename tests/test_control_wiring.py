"""P10: the Control Deck is registered in the real app (needs the p10 main.py patch)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_control_deck_is_wired_into_the_app() -> None:
    app = create_app()
    if not hasattr(app.state, "control"):
        pytest.skip("P10 main.py patch not applied yet")
    for action in ("volume.up", "mic.toggle", "macro.run", "shortcut.run", "app.activate"):
        assert app.state.actions.has(action)
    client = TestClient(app, headers={"host": "127.0.0.1:8000"})
    assert client.get("/api/control/macros").status_code == 200
    assert client.post("/hooks/nope", json={}).status_code == 404
    assert "widgets-control.js" in client.get("/panel").text
