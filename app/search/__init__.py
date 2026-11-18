"""Smart search: one question across tasks, notes, memory, Cowork and Mac files.

`SmartSearch.search` collects hits from the read-only sources in a fixed order (tasks,
notes, memory, cowork, files). `handle_voice` runs that search off the event loop and
speaks an honest answer. A file snippet is spoken only when the Files Data Consent is on;
otherwise Lupin only mentions file names. Nothing here logs file names, contents or queries.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

from app import speech
from app.search.consent import FilesConsent
from app.search.files import FileSearch
from app.search.sources import search_cowork, search_memory, search_notes, search_tasks

logger = logging.getLogger(__name__)

MAX_SPOKEN_HITS = 4
_PREFIXES = ("query:", "find:")


def _strip_prefix(target: str) -> str:
    text = target.strip()
    lowered = text.lower()
    for prefix in _PREFIXES:
        if lowered.startswith(prefix):
            return text[len(prefix):].strip()
    return text


class SmartSearch:
    """Searches every source for one query and turns the result into speech."""

    def __init__(self, store: Any, memory: Any, cowork: Any, files: Any, consent: Any) -> None:
        self._store = store
        self._memory = memory
        self._cowork = cowork
        self._files = files
        self._consent = consent

    def search(self, query: str) -> list[dict]:
        """Hits in order: tasks, notes, memory, cowork, files. Blocking (mdfind is slow)."""
        hits: list[dict] = []
        hits.extend(search_tasks(self._store, query))
        hits.extend(search_notes(self._store, query))
        hits.extend(search_memory(self._memory, query))
        hits.extend(search_cowork(self._cowork, query))
        for item in self._files.search(query):
            path = str(item.get("path") or "")
            name = str(item.get("name") or path.rsplit("/", 1)[-1])
            hits.append({"source": "files", "title": name, "path": path})
        return hits

    async def handle_voice(self, kind: str, target: str) -> dict[str, Any]:
        """Run one search; returns {ok, spoken, kind, verb, hits}."""
        query = _strip_prefix(str(target or ""))
        if not query:
            return self._failed()
        try:
            hits = await asyncio.to_thread(self.search, query)
            spoken = await self._speak(query, hits)
            return self._result(True, spoken, hits)
        except Exception as exc:
            logger.warning("Smart search failed (%s).", type(exc).__name__)
            return self._failed()

    async def _speak_files(self, query: str, hits: list[dict]) -> str:
        """Extra line about the first file hit: a snippet with consent, else names only."""
        file_hits = [hit for hit in hits if hit.get("source") == "files"]
        if not file_hits:
            return ""
        if self._consent.get() is True:
            first = file_hits[0]
            snippet = await asyncio.to_thread(self._files.snippet, first["path"], query)
            if snippet:
                return " " + speech.search_snippet(first["title"], snippet)
            return ""
        return " " + speech.search_files_names_only()

    async def _speak(self, query: str, hits: list[dict]) -> str:
        if not hits:
            return speech.search_nothing(query)
        shown = hits[:MAX_SPOKEN_HITS]
        spoken = speech.search_found(
            [(hit["source"], hit["title"]) for hit in shown], len(hits)
        )
        return spoken + await self._speak_files(query, hits)

    @staticmethod
    def _result(ok: bool, spoken: str, hits: list[dict]) -> dict[str, Any]:
        public_hits: list[dict[str, str]] = []
        for hit in hits:
            entry = {"source": hit["source"], "title": hit["title"]}
            if hit["source"] == "files":
                entry["path"] = hit["path"]
            public_hits.append(entry)
        return {"ok": ok, "spoken": spoken, "kind": "search", "verb": "query", "hits": public_hits}

    @classmethod
    def _failed(cls) -> dict[str, Any]:
        return {
            "ok": False,
            "spoken": speech.voice_action_failed(),
            "kind": "search",
            "verb": "query",
            "hits": [],
        }


def register(
    fastapi_app: Any,
    *,
    store: Any,
    memory: Any,
    cowork: Any,
    signature: Callable[[], tuple[str, str]],
    roots: Any = None,
    files: Any = None,
) -> SmartSearch:
    """Build the search and its files consent, and attach both to `fastapi_app.state`."""
    consent = FilesConsent(memory, signature)
    file_search = files if files is not None else FileSearch(roots)
    smart = SmartSearch(store, memory, cowork, file_search, consent)
    fastapi_app.state.smart_search = smart
    fastapi_app.state.files_consent = consent
    return smart
