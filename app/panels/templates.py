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

# Widget spec: (id, type, x, y, w, h, placeholder text or None for no config).
_WidgetSpec = tuple[str, str, int, int, int, int, str | None]


def _widgets(specs: tuple[_WidgetSpec, ...]) -> list[dict[str, Any]]:
    widgets: list[dict[str, Any]] = []
    for widget_id, widget_type, x, y, w, h, text in specs:
        config: dict[str, Any] = {} if text is None else {"text": text}
        widgets.append({"id": widget_id, "type": widget_type, "x": x, "y": y, "w": w, "h": h, "config": config})
    return widgets


def _template(
    template_id: str,
    name: str,
    landscape: tuple[_WidgetSpec, ...],
    portrait: tuple[_WidgetSpec, ...],
) -> dict[str, Any]:
    return {
        "id": template_id,
        "name": name,
        "version": 1,
        "grid": {
            "landscape": {"cols": 12, "rows": 6},
            "portrait": {"cols": 6, "rows": 12},
        },
        "pages": [
            {
                "id": "home",
                "title": "Home",
                "landscape": _widgets(landscape),
                "portrait": _widgets(portrait),
            }
        ],
    }


_NEW_TEMPLATE_SPECS: tuple[tuple[str, str, tuple[_WidgetSpec, ...], tuple[_WidgetSpec, ...]], ...] = (
    (
        "home",
        "Home",
        (
            ("clock-1", "clock", 0, 0, 8, 6, None),
            ("placeholder-1", "placeholder", 8, 0, 4, 3, "Tasks"),
            ("placeholder-2", "placeholder", 8, 3, 4, 3, "Shortcuts"),
        ),
        (
            ("clock-1", "clock", 0, 0, 6, 6, None),
            ("placeholder-1", "placeholder", 0, 6, 6, 3, "Tasks"),
            ("placeholder-2", "placeholder", 0, 9, 6, 3, "Shortcuts"),
        ),
    ),
    (
        "system",
        "System",
        (
            ("placeholder-1", "placeholder", 0, 0, 8, 6, "System stats"),
            ("clock-1", "clock", 8, 0, 4, 6, None),
        ),
        (
            ("placeholder-1", "placeholder", 0, 0, 6, 6, "System stats"),
            ("clock-1", "clock", 0, 6, 6, 6, None),
        ),
    ),
    (
        "ai-coding",
        "AI coding",
        (
            ("placeholder-1", "placeholder", 0, 0, 8, 6, "Claude Code sessions"),
            ("placeholder-2", "placeholder", 8, 0, 4, 6, "Shortcuts"),
        ),
        (
            ("placeholder-1", "placeholder", 0, 0, 6, 8, "Claude Code sessions"),
            ("placeholder-2", "placeholder", 0, 8, 6, 4, "Shortcuts"),
        ),
    ),
    (
        "music",
        "Music",
        (
            ("placeholder-1", "placeholder", 0, 0, 8, 6, "Now playing"),
            ("clock-1", "clock", 8, 0, 4, 6, None),
        ),
        (
            ("placeholder-1", "placeholder", 0, 0, 6, 8, "Now playing"),
            ("clock-1", "clock", 0, 8, 6, 4, None),
        ),
    ),
    (
        "planner",
        "Planner",
        (
            ("clock-1", "clock", 0, 0, 4, 6, None),
            ("placeholder-1", "placeholder", 4, 0, 8, 6, "Tasks"),
        ),
        (
            ("clock-1", "clock", 0, 0, 6, 4, None),
            ("placeholder-1", "placeholder", 0, 4, 6, 8, "Tasks"),
        ),
    ),
    (
        "control-deck",
        "Control Deck",
        (
            ("placeholder-1", "placeholder", 0, 0, 6, 6, "Shortcuts"),
            ("placeholder-2", "placeholder", 6, 0, 6, 3, "System stats"),
            ("placeholder-3", "placeholder", 6, 3, 6, 3, "Now playing"),
        ),
        (
            ("placeholder-1", "placeholder", 0, 0, 6, 6, "Shortcuts"),
            ("placeholder-2", "placeholder", 0, 6, 6, 3, "System stats"),
            ("placeholder-3", "placeholder", 0, 9, 6, 3, "Now playing"),
        ),
    ),
)

for _template_id, _name, _landscape, _portrait in _NEW_TEMPLATE_SPECS:
    TEMPLATES[_template_id] = _template(_template_id, _name, _landscape, _portrait)


def list_templates() -> list[dict[str, str]]:
    """Return the id and name of every template."""
    return [{"id": template["id"], "name": template["name"]} for template in TEMPLATES.values()]


def build_from_template(template_id: str) -> dict[str, Any]:
    """Return a deep copy of a template; raises KeyError for an unknown template."""
    return copy.deepcopy(TEMPLATES[template_id])
