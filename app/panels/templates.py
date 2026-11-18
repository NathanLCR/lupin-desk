"""Built-in Layout templates. New Layouts start from one of these."""

from __future__ import annotations

import copy
from typing import Any

STARTER_ID = "starter"

TEMPLATES: dict[str, dict[str, Any]] = {
    STARTER_ID: {
        "id": STARTER_ID,
        "name": "Starter",
        "version": 1,
        "grid": {
            "landscape": {"cols": 12, "rows": 6},
            "portrait": {"cols": 6, "rows": 12},
        },
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "landscape": [
                    {"id": "clock-1", "type": "clock", "x": 0, "y": 0, "w": 8, "h": 6, "config": {}},
                    {
                        "id": "placeholder-1",
                        "type": "placeholder",
                        "x": 8,
                        "y": 0,
                        "w": 4,
                        "h": 6,
                        "config": {"text": "Widget coming soon"},
                    },
                ],
                "portrait": [
                    {"id": "clock-1", "type": "clock", "x": 0, "y": 0, "w": 6, "h": 6, "config": {}},
                    {
                        "id": "placeholder-1",
                        "type": "placeholder",
                        "x": 0,
                        "y": 6,
                        "w": 6,
                        "h": 6,
                        "config": {"text": "Widget coming soon"},
                    },
                ],
            }
        ],
    }
}


def list_templates() -> list[dict[str, str]]:
    """Return the id and name of every template."""
    return [{"id": template["id"], "name": template["name"]} for template in TEMPLATES.values()]


def build_from_template(template_id: str) -> dict[str, Any]:
    """Return a deep copy of a template; raises KeyError for an unknown template."""
    return copy.deepcopy(TEMPLATES[template_id])
