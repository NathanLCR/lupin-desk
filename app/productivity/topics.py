"""Payloads for the productivity topics pushed to connected Bodies, and the publish helper."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

TOPICS: tuple[str, ...] = ("tasks", "notes", "habits")


def tasks_payload(store: Any, include_done: bool = False) -> dict[str, Any]:
    """Tasks for the tasks topic: open tasks only unless include_done is True."""
    return {"tasks": store.list_tasks(include_done=include_done)}


def notes_payload(store: Any) -> dict[str, Any]:
    """Notes for the notes topic, newest first."""
    return {"notes": store.list_notes()}


def habits_payload(store: Any) -> dict[str, Any]:
    """Habits (with streaks and done_today) for the habits topic."""
    return {"habits": store.list_habits()}


_PAYLOADS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "tasks": tasks_payload,
    "notes": notes_payload,
    "habits": habits_payload,
}


async def publish_changed(
    store: Any,
    publish: Callable[[str, dict[str, Any]], Awaitable[Any]] | None,
    *topics: str,
) -> None:
    """Publish the current payload of each changed topic; unknown topics are ignored.

    A failing publish is logged by exception type name only and never raised.
    """
    if publish is None:
        return
    for topic in topics:
        if topic not in TOPICS:
            continue
        try:
            await publish(topic, _PAYLOADS[topic](store))
        except Exception as exc:
            logger.warning("Productivity topic %s was not published (%s).", topic, type(exc).__name__)
