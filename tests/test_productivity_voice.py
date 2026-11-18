"""Tests for voice/LLM actions on tasks, notes and habits, plus the action tag parsing."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app import speech
from app.llm import TagStreamParser, _ACTION_TAG_RE
from app.productivity.store import ProductivityStore
from app.productivity.topics import publish_changed
from app.productivity.voice import VoiceActions

# 2026-11-18 is a Wednesday.
NOW = datetime(2026, 11, 18, 9, 0, 0)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


class FakePublish:
    """Async publish stand-in that records (topic, payload) calls."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, topic: str, payload: dict[str, Any]) -> int:
        self.calls.append((topic, payload))
        return 1


@pytest.fixture
def store(tmp_path: Path):
    productivity = ProductivityStore(tmp_path / "productivity.db", clock=FakeClock(NOW))
    yield productivity
    productivity.close()


@pytest.fixture
def publish() -> FakePublish:
    return FakePublish()


@pytest.fixture
def voice(store: ProductivityStore, publish: FakePublish) -> VoiceActions:
    return VoiceActions(store, publish)


def run(voice: VoiceActions, kind: str, target: str) -> dict[str, Any]:
    return asyncio.run(voice.handle(kind, target))


@pytest.fixture(params=["pt-BR", "en"])
def language(request: pytest.FixtureRequest) -> str:
    speech.set_language(request.param)
    return request.param


# ----------------------------------------------------------------- tasks


def test_task_add_speaks_and_publishes(voice, store, publish, language) -> None:
    result = run(voice, "task", "add:buy milk")

    assert result["ok"] is True
    assert result["kind"] == "task" and result["verb"] == "add"
    assert result["spoken"] == speech.task_added("buy milk")
    assert [t["title"] for t in store.list_tasks()] == ["buy milk"]
    assert len(publish.calls) == 1
    topic, payload = publish.calls[0]
    assert topic == "tasks"
    assert payload == {"tasks": store.list_tasks()}


def test_task_add_language_specific_wording(voice, language) -> None:
    result = run(voice, "task", "add:buy milk")
    expected = "Added to your tasks" if language == "en" else "Anotado na sua lista"
    assert expected in result["spoken"]


def test_task_done_marks_the_single_match(voice, store, publish, language) -> None:
    store.add_task("buy milk")
    store.add_task("call mom")
    publish.calls.clear()

    result = run(voice, "task", "done:milk")

    assert result["ok"] is True
    assert result["spoken"] == speech.task_done("buy milk")
    assert [t["title"] for t in store.list_tasks()] == ["call mom"]
    assert publish.calls[0][0] == "tasks"
    assert publish.calls[0][1] == {"tasks": store.list_tasks()}


def test_task_done_not_found(voice, store, publish, language) -> None:
    store.add_task("buy milk")
    publish.calls.clear()

    result = run(voice, "task", "done:laundry")

    assert result["ok"] is False
    assert result["spoken"] == speech.task_not_found("laundry")
    assert publish.calls == []


def test_task_done_ambiguity_does_not_act(voice, store, publish, language) -> None:
    store.add_task("buy milk")
    store.add_task("buy milk bread")
    publish.calls.clear()

    result = run(voice, "task", "done:buy milk")

    assert result["ok"] is False
    assert result["spoken"] == speech.ambiguous("buy milk", ["buy milk", "buy milk bread"])
    assert all(not t["done"] for t in store.list_tasks(include_done=True))
    assert publish.calls == []


def test_task_remove_deletes_and_publishes(voice, store, publish, language) -> None:
    store.add_task("buy milk")
    publish.calls.clear()

    result = run(voice, "task", "remove:milk")

    assert result["ok"] is True
    assert result["spoken"] == speech.task_removed("buy milk")
    assert store.list_tasks(include_done=True) == []
    assert publish.calls[0][0] == "tasks"


def test_task_remove_not_found(voice, publish, language) -> None:
    result = run(voice, "task", "remove:ghost")
    assert result["ok"] is False
    assert result["spoken"] == speech.task_not_found("ghost")
    assert publish.calls == []


def test_task_list_speaks_first_five_and_never_publishes(voice, store, publish, language) -> None:
    for index in range(7):
        store.add_task(f"task {index}")
    publish.calls.clear()

    result = run(voice, "task", "list")

    assert result["ok"] is True
    assert result["spoken"] == speech.tasks_list(
        [f"task {index}" for index in range(5)], total=7
    )
    assert "task 4" in result["spoken"] and "task 5" not in result["spoken"]
    assert publish.calls == []


def test_task_list_empty(voice, publish, language) -> None:
    result = run(voice, "task", "list")
    assert result["ok"] is True
    assert result["spoken"] == speech.tasks_none()
    assert publish.calls == []


# ----------------------------------------------------------------- notes


def test_note_add_and_list(voice, store, publish, language) -> None:
    added = run(voice, "note", "add:call the dentist")
    assert added["ok"] is True
    assert added["spoken"] == speech.note_added("call the dentist")
    assert publish.calls[-1][0] == "notes"
    assert publish.calls[-1][1] == {"notes": store.list_notes()}

    publish.calls.clear()
    listed = run(voice, "note", "list")
    assert listed["ok"] is True
    assert listed["spoken"] == speech.notes_list(["call the dentist"], total=1)
    assert publish.calls == []


def test_note_list_empty(voice, language) -> None:
    result = run(voice, "note", "list")
    assert result["spoken"] == speech.notes_none()


# ----------------------------------------------------------------- habits


def test_habit_add_with_time_is_zero_padded(voice, store, publish, language) -> None:
    result = run(voice, "habit", "add:read@7:05")

    assert result["ok"] is True
    assert result["spoken"] == speech.habit_added("read", "07:05")
    habits = store.list_habits()
    assert habits[0]["name"] == "read"
    assert habits[0]["time"] == "07:05"
    assert publish.calls[0][0] == "habits"
    assert publish.calls[0][1] == {"habits": store.list_habits()}


def test_habit_add_keeps_at_sign_without_time_suffix(voice, store, language) -> None:
    run(voice, "habit", "add:email@work")
    habit = store.list_habits()[0]
    assert habit["name"] == "email@work"
    assert habit["time"] is None


def test_habit_add_splits_on_last_at_only(voice, store, language) -> None:
    run(voice, "habit", "add:a@b@08:00")
    habit = store.list_habits()[0]
    assert habit["name"] == "a@b"
    assert habit["time"] == "08:00"


def test_habit_check_with_streak(voice, store, publish, language) -> None:
    habit = store.add_habit("drink water")
    store.check_in(habit["id"], day="2026-11-17")
    publish.calls.clear()

    result = run(voice, "habit", "check:water")

    assert result["ok"] is True
    assert result["spoken"] == speech.habit_checked("drink water", 2)
    assert "2" in result["spoken"]
    assert store.list_habits()[0]["done_today"] is True
    assert publish.calls[0][0] == "habits"


def test_habit_check_first_day_has_no_streak_wording(voice, store, language) -> None:
    store.add_habit("drink water")
    result = run(voice, "habit", "check:drink")
    assert result["spoken"] == speech.habit_checked("drink water", 1)


def test_habit_check_not_found_and_ambiguous(voice, store, publish, language) -> None:
    store.add_habit("drink water")
    store.add_habit("drink tea")
    publish.calls.clear()

    missing = run(voice, "habit", "check:yoga")
    assert missing["ok"] is False
    assert missing["spoken"] == speech.habit_not_found("yoga")

    ambiguous = run(voice, "habit", "check:drink")
    assert ambiguous["ok"] is False
    assert ambiguous["spoken"] == speech.ambiguous("drink", ["drink water", "drink tea"])
    assert all(not h["done_today"] for h in store.list_habits())
    assert publish.calls == []


def test_habit_list_marks_done_today_and_never_publishes(voice, store, publish, language) -> None:
    water = store.add_habit("drink water")
    store.add_habit("read")
    store.check_in(water["id"])
    publish.calls.clear()

    result = run(voice, "habit", "list")

    assert result["ok"] is True
    assert result["spoken"] == speech.habits_list(
        ["drink water", "read"], {"drink water"}, total=2
    )
    assert publish.calls == []


# ----------------------------------------------------------------- failures and publishing


@pytest.mark.parametrize(
    ("kind", "target"),
    [
        ("task", "add:"),
        ("task", "add:   "),
        ("task", "done:"),
        ("task", "explode:now"),
        ("note", "add:"),
        ("note", "frobnicate"),
        ("habit", "add:@08:00"),
        ("habit", "add:drink@25:00"),
        ("habit", "check:"),
        ("calendar", "add:meeting"),
        ("", ""),
    ],
)
def test_bad_input_is_a_failed_action(voice, store, publish, kind, target) -> None:
    speech.set_language("en")
    result = run(voice, kind, target)

    assert result["ok"] is False
    assert result["spoken"] == speech.voice_action_failed()
    assert store.list_tasks(include_done=True) == []
    assert store.list_notes() == []
    assert store.list_habits() == []
    assert publish.calls == []


def test_unexpected_exception_is_contained(store, language) -> None:
    class BrokenStore:
        def add_task(self, title: str):
            raise RuntimeError("secret detail should not leak")

    voice = VoiceActions(BrokenStore(), FakePublish())
    result = run(voice, "task", "add:buy milk")

    assert result["ok"] is False
    assert result["spoken"] == speech.voice_action_failed()
    assert "secret" not in result["spoken"]


def test_publish_failure_does_not_fail_the_action(store, language) -> None:
    async def broken_publish(topic: str, payload: dict[str, Any]) -> int:
        raise ConnectionError("hub down")

    voice = VoiceActions(store, broken_publish)
    result = run(voice, "task", "add:buy milk")

    assert result["ok"] is True
    assert [t["title"] for t in store.list_tasks()] == ["buy milk"]


def test_publish_changed_ignores_unknown_topics_and_none(store) -> None:
    recorder = FakePublish()
    asyncio.run(publish_changed(store, recorder, "tasks", "weather", "habits"))
    assert [topic for topic, _ in recorder.calls] == ["tasks", "habits"]

    asyncio.run(publish_changed(store, None, "tasks"))  # no publish: must not raise


def test_voice_without_publish_still_acts(store, language) -> None:
    voice = VoiceActions(store, None)
    result = run(voice, "note", "add:remember the milk")
    assert result["ok"] is True
    assert store.list_notes()[0]["text"] == "remember the milk"


# ----------------------------------------------------------------- LLM tag parsing


def test_action_tag_regex_accepts_productivity_kinds() -> None:
    match = _ACTION_TAG_RE.match("[action:task:add:buy milk]")
    assert match is not None
    assert match.group(1) == "task"
    assert match.group(2) == "add:buy milk"


def test_stream_parser_emits_task_action_event() -> None:
    parser = TagStreamParser()
    events = parser.feed("[emotion:happy] Sure. [action:task:add:buy milk]")
    events += parser.feed("")
    finals = parser.finish()[0]
    all_events = events + list(finals)
    assert {"type": "action", "kind": "task", "target": "add:buy milk"} in all_events


def test_persona_prompt_documents_productivity_tags_in_both_languages() -> None:
    for lang in ("en", "pt-BR"):
        speech.set_language(lang)
        prompt = speech.persona_prompt("happy, sad")
        assert "[action:task:add:" in prompt
        assert "[action:note:list]" in prompt
        assert "[action:habit:check:" in prompt
        assert "[action:today:brief]" in prompt
    speech.set_language("pt-BR")
