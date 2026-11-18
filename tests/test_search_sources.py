"""Search sources tests: tasks, notes, memory and Cowork, read only, never raising."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT_DIR = str(Path(__file__).resolve().parent.parent)
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)

from app.productivity.store import ProductivityStore
from app.search.sources import search_cowork, search_memory, search_notes, search_tasks


class FakeStore:
    def __init__(self, tasks: list[dict[str, Any]] | None = None, notes: list[dict[str, Any]] | None = None) -> None:
        self.tasks = tasks or []
        self.notes = notes or []
        self.include_done_seen: list[bool] = []

    def find_tasks(self, query: str, include_done: bool = False) -> list[dict[str, Any]]:
        self.include_done_seen.append(include_done)
        return list(self.tasks)

    def find_notes(self, query: str) -> list[dict[str, Any]]:
        return list(self.notes)


class FakeMemory:
    def __init__(self, facts: list[str]) -> None:
        self.facts = facts

    def get_facts(self, include_superseded: bool = False) -> list[dict[str, Any]]:
        return [{"key": f"k{i}", "fact": text} for i, text in enumerate(self.facts)]


class FakeCowork:
    def __init__(self, state: dict[str, Any]) -> None:
        self.state = state

    def load_state(self) -> dict[str, Any]:
        return self.state


class BrokenStore:
    def find_tasks(self, query: str, include_done: bool = False) -> list[dict[str, Any]]:
        raise RuntimeError("boom")

    def find_notes(self, query: str) -> list[dict[str, Any]]:
        raise RuntimeError("boom")


EMPTY_QUERIES = ["", "   "]


@pytest.mark.parametrize("query", EMPTY_QUERIES)
def test_empty_query_returns_nothing(query: str) -> None:
    store = FakeStore(tasks=[{"title": "Anything"}], notes=[{"text": "Anything"}])
    assert search_tasks(store, query) == []
    assert search_notes(store, query) == []
    assert search_memory(FakeMemory(["Anything"]), query) == []
    assert search_cowork(FakeCowork({"workspace_exists": True, "tasks": [{"title": "Anything"}]}), query) == []


def test_non_string_query_returns_nothing() -> None:
    assert search_tasks(FakeStore(tasks=[{"title": "x"}]), None) == []  # type: ignore[arg-type]


def test_tasks_use_find_tasks_with_done_included_and_source() -> None:
    store = FakeStore(tasks=[{"id": 1, "title": "Pagar conta", "done": True}])
    hits = search_tasks(store, "conta")
    assert hits == [{"source": "tasks", "title": "Pagar conta"}]
    assert store.include_done_seen == [True]


def test_notes_short_text_is_title_unchanged() -> None:
    store = FakeStore(notes=[{"id": 1, "text": "Comprar pilha AA"}])
    assert search_notes(store, "pilha") == [{"source": "notes", "title": "Comprar pilha AA"}]


def test_notes_long_text_is_cut_to_80_with_ellipsis() -> None:
    text = "a" * 100
    hits = search_notes(FakeStore(notes=[{"text": text}]), "aaa")
    assert hits == [{"source": "notes", "title": "a" * 80 + "..."}]


def test_notes_text_of_exactly_80_chars_is_not_cut() -> None:
    text = "b" * 80
    hits = search_notes(FakeStore(notes=[{"text": text}]), "bbb")
    assert hits == [{"source": "notes", "title": text}]


def test_memory_requires_every_word_accent_and_case_insensitive() -> None:
    memory = FakeMemory(["Gosta de Café forte", "Gosta de café", "Mora em Curitiba"])
    hits = search_memory(memory, "CAFE forte")
    assert hits == [{"source": "memory", "title": "Gosta de Café forte"}]


def test_memory_no_match_returns_empty() -> None:
    assert search_memory(FakeMemory(["Mora em Curitiba"]), "praia") == []


def test_cowork_titles_with_due_and_deadline_date() -> None:
    cowork = FakeCowork(
        {
            "workspace_exists": True,
            "tasks": [
                {"title": "Revisar relatório", "status": "open", "due": "2026-11-20"},
                {"title": "Relatório antigo", "status": "done"},
                {"title": "Outra coisa", "status": "open"},
            ],
            "deadlines": [{"title": "Entrega do relatório", "date": "2026-12-01"}],
        }
    )
    hits = search_cowork(cowork, "RELATORIO")
    assert hits == [
        {"source": "cowork", "title": "Revisar relatório (due 2026-11-20)"},
        {"source": "cowork", "title": "Relatório antigo"},
        {"source": "cowork", "title": "Entrega do relatório (on 2026-12-01)"},
    ]


def test_cowork_without_workspace_returns_empty() -> None:
    cowork = FakeCowork({"workspace_exists": False, "tasks": [{"title": "Relatório"}]})
    assert search_cowork(cowork, "relatorio") == []


def test_sources_never_raise_on_error() -> None:
    assert search_tasks(BrokenStore(), "x") == []
    assert search_notes(BrokenStore(), "x") == []
    assert search_memory(object(), "x") == []
    assert search_cowork(object(), "x") == []


def test_tasks_and_notes_with_real_productivity_store(tmp_path: Path) -> None:
    store = ProductivityStore(tmp_path / "s.db")
    try:
        store.add_task("Comprar café")
        done = store.add_task("Ligar pro dentista")
        store.set_task_done(done["id"], True)
        store.add_note("Ideia: " + "x" * 120)

        task_hits = search_tasks(store, "cafe")
        assert task_hits == [{"source": "tasks", "title": "Comprar café"}]

        dentist = search_tasks(store, "dentista")
        assert dentist == [{"source": "tasks", "title": "Ligar pro dentista"}]

        note_hits = search_notes(store, "ideia")
        assert len(note_hits) == 1
        assert note_hits[0]["source"] == "notes"
        assert note_hits[0]["title"].endswith("...")
        assert len(note_hits[0]["title"]) == 83
    finally:
        store._conn.close()
