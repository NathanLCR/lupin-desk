"""Tests for the smart search orchestrator and its voice answer (fakes only)."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app import speech
from app.search import MAX_SPOKEN_HITS, SmartSearch, register


class FakeStore:
    def __init__(self, tasks: list[str] | None = None, notes: list[str] | None = None) -> None:
        self._tasks = tasks or []
        self._notes = notes or []
        self.queries: list[str] = []

    def find_tasks(self, query: str, include_done: bool = False) -> list[dict[str, Any]]:
        self.queries.append(query)
        return [{"title": title} for title in self._tasks]

    def find_notes(self, query: str) -> list[dict[str, Any]]:
        return [{"text": text} for text in self._notes]


class FakeMemory:
    def __init__(self, facts: list[str] | None = None) -> None:
        self._facts = facts or []

    def get_facts(self) -> list[dict[str, Any]]:
        return [{"fact": fact} for fact in self._facts]


class FakeCowork:
    def __init__(self, tasks: list[str] | None = None) -> None:
        self._tasks = tasks or []

    def load_state(self) -> dict[str, Any]:
        return {
            "workspace_exists": True,
            "tasks": [{"title": title} for title in self._tasks],
            "deadlines": [],
        }


class FakeFiles:
    def __init__(
        self,
        names: list[str] | None = None,
        snippet_text: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self._names = names or []
        self._snippet_text = snippet_text
        self._error = error
        self.snippet_calls: list[tuple[str, str]] = []

    def search(self, query: str) -> list[dict[str, str]]:
        if self._error is not None:
            raise self._error
        return [{"path": f"/Users/someone/Documents/{name}", "name": name} for name in self._names]

    def snippet(self, path: str, query: str) -> str | None:
        self.snippet_calls.append((path, query))
        if self._snippet_text is None:
            return None
        return self._snippet_text


class FakeConsent:
    def __init__(self, value: bool) -> None:
        self._value = value

    def get(self) -> bool:
        return self._value


def make_search(
    *,
    tasks: list[str] | None = None,
    notes: list[str] | None = None,
    facts: list[str] | None = None,
    cowork: list[str] | None = None,
    files: FakeFiles | None = None,
    consent: bool = False,
) -> SmartSearch:
    return SmartSearch(
        FakeStore(tasks, notes),
        FakeMemory(facts),
        FakeCowork(cowork),
        files or FakeFiles(),
        FakeConsent(consent),
    )


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def language():
    """Run a test in a chosen language and restore pt-BR afterwards."""
    def set_lang(code: str) -> None:
        speech.set_language(code)

    yield set_lang
    speech.set_language("pt-BR")


def test_hits_from_all_sources_are_combined_in_order():
    search = make_search(
        tasks=["buy milk"],
        notes=["milk for the cat"],
        facts=["Nathan likes milk"],
        cowork=["milk report"],
        files=FakeFiles(names=["milk.txt"]),
    )

    hits = search.search("milk")

    assert [hit["source"] for hit in hits] == ["tasks", "notes", "memory", "cowork", "files"]
    assert hits[-1] == {
        "source": "files",
        "title": "milk.txt",
        "path": "/Users/someone/Documents/milk.txt",
    }


def test_no_hits_speaks_nothing_found_and_succeeds():
    result = run(make_search().handle_voice("search", "unicorn"))

    assert result["ok"] is True
    assert result["kind"] == "search"
    assert result["verb"] == "query"
    assert result["hits"] == []
    assert result["spoken"] == speech.search_nothing("unicorn")


def test_spoken_output_caps_at_four_with_full_total():
    tasks = [f"milk task {n}" for n in range(6)]
    search = make_search(tasks=tasks)

    result = run(search.handle_voice("search", "milk"))

    shown = [("tasks", title) for title in tasks[:MAX_SPOKEN_HITS]]
    assert result["ok"] is True
    assert result["spoken"] == speech.search_found(shown, 6)
    assert "milk task 3" in result["spoken"]
    assert "milk task 4" not in result["spoken"]
    assert len(result["hits"]) == 6


def test_snippet_is_spoken_when_consent_is_on():
    files = FakeFiles(names=["shopping.txt"], snippet_text="buy milk on Sunday")
    search = make_search(files=files, consent=True)

    result = run(search.handle_voice("search", "milk"))

    assert result["ok"] is True
    assert speech.search_snippet("shopping.txt", "buy milk on Sunday") in result["spoken"]
    assert files.snippet_calls == [("/Users/someone/Documents/shopping.txt", "milk")]
    assert "buy milk on Sunday" not in str(result["hits"])


def test_snippet_is_never_read_without_consent():
    class StrictFiles(FakeFiles):
        def snippet(self, path: str, query: str) -> str | None:
            raise AssertionError("snippet must not be read without consent")

    search = make_search(files=StrictFiles(names=["secret.txt"]), consent=False)

    result = run(search.handle_voice("search", "secret"))

    assert result["ok"] is True
    assert "secret.txt" in result["spoken"]
    assert speech.search_snippet("secret.txt", "anything") not in result["spoken"]


def test_names_only_line_when_consent_off_and_file_hit_exists():
    search = make_search(files=FakeFiles(names=["report.pdf"]), consent=False)

    result = run(search.handle_voice("search", "report"))

    assert result["ok"] is True
    assert result["spoken"].endswith(speech.search_files_names_only())


def test_no_names_only_line_without_file_hits():
    search = make_search(tasks=["report"], consent=False)

    result = run(search.handle_voice("search", "report"))

    assert result["ok"] is True
    assert speech.search_files_names_only() not in result["spoken"]


def test_empty_query_fails():
    search = make_search(tasks=["anything"])

    for target in ("", "   ", "query:", "find:  "):
        result = run(search.handle_voice("search", target))
        assert result["ok"] is False
        assert result["spoken"] == speech.voice_action_failed()
        assert result["kind"] == "search"


def test_exception_in_a_source_fails_without_leaking_the_query(caplog):
    files = FakeFiles(error=RuntimeError("secretquery inside a file body"))
    search = make_search(files=files)

    with caplog.at_level(logging.DEBUG):
        result = run(search.handle_voice("search", "secretquery"))

    assert result["ok"] is False
    assert result["spoken"] == speech.voice_action_failed()
    assert result["hits"] == []
    assert "secretquery" not in caplog.text
    assert "file body" not in caplog.text


@pytest.mark.parametrize("code", ["en", "pt-BR"])
def test_answers_follow_the_language(language, code):
    language(code)
    search = make_search(tasks=["buy milk"], files=FakeFiles(names=["list.txt"]), consent=False)

    result = run(search.handle_voice("search", "milk"))

    assert result["spoken"] == (
        speech.search_found([("tasks", "buy milk"), ("files", "list.txt")], 2)
        + " "
        + speech.search_files_names_only()
    )
    assert speech.get_language() == code


@pytest.mark.parametrize("code", ["en", "pt-BR"])
def test_nothing_found_follows_the_language(language, code):
    language(code)

    result = run(make_search().handle_voice("search", "unicorn"))

    assert result["spoken"] == speech.search_nothing("unicorn")


def test_query_prefix_is_stripped_before_searching():
    store = FakeStore(tasks=["buy milk"])
    search = SmartSearch(store, FakeMemory(), FakeCowork(), FakeFiles(), FakeConsent(False))

    for target in ("query: milk", "Find: milk", "milk"):
        run(search.handle_voice("search", target))

    assert store.queries == ["milk", "milk", "milk"]


def test_register_attaches_search_and_consent_to_app_state():
    app = SimpleNamespace(state=SimpleNamespace())

    smart = register(
        app,
        store=FakeStore(),
        memory=FakeMemory(),
        cowork=FakeCowork(),
        signature=lambda: ("anthropic", "https://api.anthropic.com"),
        files=FakeFiles(),
    )

    assert isinstance(smart, SmartSearch)
    assert app.state.smart_search is smart
    assert app.state.files_consent is not None


def test_search_action_tag_is_parsed() -> None:
    from app.llm import _ACTION_TAG_RE

    match = _ACTION_TAG_RE.match("[action:search:contrato da Carla]")
    assert match is not None
    assert match.group(1) == "search" and match.group(2) == "contrato da Carla"
