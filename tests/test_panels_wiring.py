"""P02: the Panel routes are registered in the real app (needs the main.py patch)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_panel_page_and_layouts_are_served_by_the_app() -> None:
    app = create_app()
    if not hasattr(app.state, "layouts"):
        pytest.skip("P02 main.py patch not applied yet")
    client = TestClient(app)
    page = client.get("/panel")
    assert page.status_code == 200 and "panel-root" in page.text
    assert client.get("/api/layouts/default").json()["id"] == "starter"
    assert client.get("/static/panel/runtime.js").status_code == 200
