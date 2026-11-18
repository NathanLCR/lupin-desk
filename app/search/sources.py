"""Read-only search sources for Lupin's search: tasks, notes, memory and Cowork.

Each function returns a list of hit dicts ``{"source": str, "title": str}``.
They never raise: any failure yields an empty list. Matching is case and accent
insensitive, and every word of the query must appear in the text.
"""

from __future__ import annotations

import unicodedata
from typing import Any

_NOTE_TITLE_MAX = 80


def _fold(text: Any) -> str:
    """Lowercase and strip accents (NFKD, combining marks dropped)."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return stripped.casefold()


def _query_words(query: Any) -> list[str]:
    if not isinstance(query, str):
        return []
    return _fold(query).split()


def _matches(text: Any, words: list[str]) -> bool:
    if not words:
        return False
    folded = _fold(text)
    return all(word in folded for word in words)


def search_tasks(store: Any, query: str) -> list[dict[str, str]]:
    """Tasks whose title matches the query, done ones included."""
    words = _query_words(query)
    if not words:
        return []
    try:
        found = store.find_tasks(query, include_done=True)
        return [
            {"source": "tasks", "title": str(task["title"])}
            for task in found
            if isinstance(task, dict) and task.get("title")
        ]
    except Exception:
        return []


def search_notes(store: Any, query: str) -> list[dict[str, str]]:
    """Notes containing the query; the title is the note text cut to 80 chars."""
    words = _query_words(query)
    if not words:
        return []
    try:
        found = store.find_notes(query)
        hits: list[dict[str, str]] = []
        for note in found:
            if not isinstance(note, dict):
                continue
            text = str(note.get("text") or "")
            if len(text) > _NOTE_TITLE_MAX:
                text = text[:_NOTE_TITLE_MAX] + "..."
            hits.append({"source": "notes", "title": text})
        return hits
    except Exception:
        return []


def search_memory(memory: Any, query: str) -> list[dict[str, str]]:
    """Remembered facts whose text contains every query word."""
    words = _query_words(query)
    if not words:
        return []
    try:
        hits: list[dict[str, str]] = []
        for item in memory.get_facts():
            if not isinstance(item, dict):
                continue
            fact = str(item.get("fact") or "")
            if fact and _matches(fact, words):
                hits.append({"source": "memory", "title": fact})
        return hits
    except Exception:
        return []


def search_cowork(cowork: Any, query: str) -> list[dict[str, str]]:
    """Cowork tasks and deadlines whose title matches the query. Read only."""
    words = _query_words(query)
    if not words:
        return []
    try:
        state = cowork.load_state()
        if not state.get("workspace_exists"):
            return []
        hits: list[dict[str, str]] = []
        for task in state.get("tasks") or []:
            if not isinstance(task, dict) or not task.get("title"):
                continue
            title = str(task["title"])
            if not _matches(title, words):
                continue
            if task.get("due"):
                title = f"{title} (due {task['due']})"
            hits.append({"source": "cowork", "title": title})
        for deadline in state.get("deadlines") or []:
            if not isinstance(deadline, dict) or not deadline.get("title"):
                continue
            title = str(deadline["title"])
            if not _matches(title, words):
                continue
            if deadline.get("date"):
                title = f"{title} (on {deadline['date']})"
            hits.append({"source": "cowork", "title": title})
        return hits
    except Exception:
        return []
