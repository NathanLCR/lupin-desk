"""Voice and LLM actions for tasks, notes and habits: `[action:<kind>:<verb>:<arg>]` tags.

The LLM tag is split by the caller into `kind` ("task", "note" or "habit") and `target`
("add:buy milk"). This module runs the store action and returns what Lupin says aloud,
taken from the speech tables at call time so the language switch applies.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Awaitable, Callable

from app import speech
from app.productivity.topics import publish_changed

logger = logging.getLogger(__name__)

LIST_SPOKEN_MAX = 5
NOTE_SPOKEN_MAX = 80
_TIME_SUFFIX_RE = re.compile(r"(\d{1,2}):(\d{2})")
_TOPIC_BY_KIND = {"task": "tasks", "note": "notes", "habit": "habits"}

# A handler returns (ok, spoken, changed): ok is whether the request was carried out,
# changed is whether stored data changed (so the topic must be published).
Outcome = tuple[bool, str, bool]


def _short(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _split_habit_time(arg: str) -> tuple[str, str | None]:
    """Split "name@HH:MM" on the last "@" when the suffix is a time; zero-pad the hour."""
    name, sep, suffix = arg.rpartition("@")
    if sep:
        match = _TIME_SUFFIX_RE.fullmatch(suffix.strip())
        if match:
            return name.strip(), f"{int(match.group(1)):02d}:{match.group(2)}"
    return arg, None


class VoiceActions:
    """Runs task, note and habit actions for the voice/LLM path."""

    def __init__(
        self,
        store: Any,
        publish: Callable[[str, dict[str, Any]], Awaitable[Any]] | None = None,
    ) -> None:
        self._store = store
        self._publish = publish

    async def handle(self, kind: str, target: str) -> dict[str, Any]:
        """Run one action; returns {ok, spoken, kind, verb}."""
        kind_norm = str(kind or "").strip().lower()
        verb, _, arg = str(target or "").partition(":")
        verb = verb.strip().lower()
        arg = arg.strip()
        handler = self._handlers().get((kind_norm, verb))
        if handler is None:
            return self._failed(kind_norm, verb)
        try:
            ok, spoken, changed = handler(arg)
        except ValueError:
            return self._failed(kind_norm, verb)
        except Exception as exc:
            logger.warning("Voice productivity action failed (%s).", type(exc).__name__)
            return self._failed(kind_norm, verb)

        if changed:
            await publish_changed(self._store, self._publish, _TOPIC_BY_KIND[kind_norm])
        return {"ok": ok, "spoken": spoken, "kind": kind_norm, "verb": verb}

    def _handlers(self) -> dict[tuple[str, str], Callable[[str], Outcome]]:
        return {
            ("task", "add"): self._task_add,
            ("task", "done"): self._task_done,
            ("task", "remove"): self._task_remove,
            ("task", "list"): self._task_list,
            ("note", "add"): self._note_add,
            ("note", "list"): self._note_list,
            ("habit", "add"): self._habit_add,
            ("habit", "check"): self._habit_check,
            ("habit", "list"): self._habit_list,
        }

    @staticmethod
    def _failed(kind: str, verb: str) -> dict[str, Any]:
        return {
            "ok": False,
            "spoken": speech.voice_action_failed(),
            "kind": kind,
            "verb": verb,
        }

    @staticmethod
    def _require(arg: str) -> str:
        if not arg:
            raise ValueError("missing argument")
        return arg

    # ----------------------------------------------------------------- tasks

    def _task_add(self, arg: str) -> Outcome:
        task = self._store.add_task(self._require(arg))
        return True, speech.task_added(task["title"]), True

    def _task_done(self, arg: str) -> Outcome:
        query = self._require(arg)
        matches = self._store.find_tasks(query, include_done=False)
        if not matches:
            return False, speech.task_not_found(query), False
        if len(matches) > 1:
            return False, speech.ambiguous(query, [task["title"] for task in matches]), False
        task = self._store.set_task_done(matches[0]["id"], True)
        if task is None:
            return False, speech.task_not_found(query), False
        return True, speech.task_done(task["title"]), True

    def _task_remove(self, arg: str) -> Outcome:
        query = self._require(arg)
        matches = self._store.find_tasks(query, include_done=True)
        if not matches:
            return False, speech.task_not_found(query), False
        if len(matches) > 1:
            return False, speech.ambiguous(query, [task["title"] for task in matches]), False
        task = matches[0]
        if not self._store.remove_task(task["id"]):
            return False, speech.task_not_found(query), False
        return True, speech.task_removed(task["title"]), True

    def _task_list(self, _arg: str) -> Outcome:
        tasks = self._store.list_tasks(include_done=False)
        if not tasks:
            return True, speech.tasks_none(), False
        titles = [task["title"] for task in tasks[:LIST_SPOKEN_MAX]]
        return True, speech.tasks_list(titles, total=len(tasks)), False

    # ----------------------------------------------------------------- notes

    def _note_add(self, arg: str) -> Outcome:
        note = self._store.add_note(self._require(arg))
        return True, speech.note_added(note["text"]), True

    def _note_list(self, _arg: str) -> Outcome:
        notes = self._store.list_notes()
        if not notes:
            return True, speech.notes_none(), False
        texts = [_short(note["text"], NOTE_SPOKEN_MAX) for note in notes[:LIST_SPOKEN_MAX]]
        return True, speech.notes_list(texts, total=len(notes)), False

    # ---------------------------------------------------------------- habits

    def _habit_add(self, arg: str) -> Outcome:
        name, time = _split_habit_time(self._require(arg))
        habit = self._store.add_habit(self._require(name), time=time)
        return True, speech.habit_added(habit["name"], habit["time"]), True

    def _habit_check(self, arg: str) -> Outcome:
        query = self._require(arg)
        matches = self._store.find_habits(query)
        if not matches:
            return False, speech.habit_not_found(query), False
        if len(matches) > 1:
            return False, speech.ambiguous(query, [habit["name"] for habit in matches]), False
        habit = self._store.check_in(matches[0]["id"], done=True)
        if habit is None:
            return False, speech.habit_not_found(query), False
        return True, speech.habit_checked(habit["name"], habit["streak"]), True

    def _habit_list(self, _arg: str) -> Outcome:
        habits = self._store.list_habits()
        if not habits:
            return True, speech.habits_none(), False
        shown = habits[:LIST_SPOKEN_MAX]
        names = [habit["name"] for habit in shown]
        done = {habit["name"] for habit in shown if habit["done_today"]}
        return True, speech.habits_list(names, done, total=len(habits)), False
