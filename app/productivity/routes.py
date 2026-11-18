"""HTTP routes for tasks, notes and habits, and the Panel actions that mirror them.

These routes are LAN-trusted like the other Panel-facing API, so there is no Mac-only guard.
Every successful mutation publishes the full list payload of the changed topic to the Bodies.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from app.actions import ActionRegistry
from app.productivity.store import HABIT_NAME_MAX, NOTE_MAX, TITLE_MAX
from app.productivity.topics import (
    habits_payload,
    notes_payload,
    publish_changed,
    tasks_payload,
)

Publish = Callable[[str, dict[str, Any]], Awaitable[Any]] | None


class TaskCreate(BaseModel):
    title: str = Field(max_length=TITLE_MAX)


class TaskPatch(BaseModel):
    """Only `done` can change today; a body without it is rejected."""

    done: bool | None = None


class NoteCreate(BaseModel):
    text: str = Field(max_length=NOTE_MAX)


class HabitCreate(BaseModel):
    name: str = Field(max_length=HABIT_NAME_MAX)
    days: list[int] | None = None
    time: str | None = None


class HabitCheckin(BaseModel):
    done: bool = True
    day: str | None = None


def _id_arg(args: dict[str, Any], key: str = "id") -> int:
    value = args.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{key} must be an integer")
    return value


def _text_arg(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a string")
    return value


def _optional_bool_arg(args: dict[str, Any], key: str) -> bool | None:
    value = args.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ValueError(f"{key} must be a boolean")
    return value


def setup_routes(fastapi_app: FastAPI, store: Any, publish: Publish) -> None:
    """Register the task, note and habit REST routes on the app."""

    def _not_found(what: str) -> HTTPException:
        return HTTPException(status_code=404, detail=f"Unknown {what}.")

    @fastapi_app.get("/api/tasks")
    def list_tasks(include_done: bool = False) -> dict[str, Any]:
        return tasks_payload(store, include_done)

    @fastapi_app.post("/api/tasks")
    async def create_task(payload: TaskCreate) -> dict[str, Any]:
        try:
            task = store.add_task(payload.title)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await publish_changed(store, publish, "tasks")
        return task

    @fastapi_app.patch("/api/tasks/{task_id}")
    async def update_task(task_id: int, payload: TaskPatch) -> dict[str, Any]:
        if payload.done is None:
            raise HTTPException(status_code=422, detail="done must be true or false.")
        task = store.set_task_done(task_id, payload.done)
        if task is None:
            raise _not_found("task")
        await publish_changed(store, publish, "tasks")
        return task

    @fastapi_app.delete("/api/tasks/{task_id}")
    async def delete_task(task_id: int) -> dict[str, bool]:
        if not store.remove_task(task_id):
            raise _not_found("task")
        await publish_changed(store, publish, "tasks")
        return {"ok": True}

    @fastapi_app.get("/api/notes")
    def list_notes() -> dict[str, Any]:
        return notes_payload(store)

    @fastapi_app.post("/api/notes")
    async def create_note(payload: NoteCreate) -> dict[str, Any]:
        try:
            note = store.add_note(payload.text)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await publish_changed(store, publish, "notes")
        return note

    @fastapi_app.delete("/api/notes/{note_id}")
    async def delete_note(note_id: int) -> dict[str, bool]:
        if not store.remove_note(note_id):
            raise _not_found("note")
        await publish_changed(store, publish, "notes")
        return {"ok": True}

    @fastapi_app.get("/api/habits")
    def list_habits() -> dict[str, Any]:
        return habits_payload(store)

    @fastapi_app.post("/api/habits")
    async def create_habit(payload: HabitCreate) -> dict[str, Any]:
        try:
            habit = store.add_habit(payload.name, days=payload.days, time=payload.time)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        await publish_changed(store, publish, "habits")
        return habit

    @fastapi_app.post("/api/habits/{habit_id}/checkin")
    async def checkin_habit(habit_id: int, payload: HabitCheckin) -> dict[str, Any]:
        try:
            habit = store.check_in(habit_id, day=payload.day, done=payload.done)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if habit is None:
            raise _not_found("habit")
        await publish_changed(store, publish, "habits")
        return habit

    @fastapi_app.delete("/api/habits/{habit_id}")
    async def delete_habit(habit_id: int) -> dict[str, bool]:
        if not store.remove_habit(habit_id):
            raise _not_found("habit")
        await publish_changed(store, publish, "habits")
        return {"ok": True}


def setup_actions(actions: ActionRegistry, store: Any, publish: Publish) -> None:
    """Register the Panel actions for tasks, notes and habits.

    Handlers raise ValueError for bad or unknown arguments; ActionRegistry turns that into
    action_failed. Each successful mutation publishes its topic.
    """

    def _find_task(task_id: int) -> dict[str, Any]:
        for task in store.list_tasks(include_done=True):
            if task["id"] == task_id:
                return task
        raise ValueError("unknown task id")

    async def tasks_add(args: dict[str, Any]) -> dict[str, Any]:
        task = store.add_task(_text_arg(args, "title"))
        await publish_changed(store, publish, "tasks")
        return task

    async def tasks_toggle(args: dict[str, Any]) -> dict[str, Any]:
        task_id = _id_arg(args)
        done = _optional_bool_arg(args, "done")
        if done is None:
            done = not _find_task(task_id)["done"]
        task = store.set_task_done(task_id, done)
        if task is None:
            raise ValueError("unknown task id")
        await publish_changed(store, publish, "tasks")
        return task

    async def tasks_remove(args: dict[str, Any]) -> dict[str, Any]:
        task_id = _id_arg(args)
        if not store.remove_task(task_id):
            raise ValueError("unknown task id")
        await publish_changed(store, publish, "tasks")
        return {"id": task_id, "removed": True}

    async def notes_add(args: dict[str, Any]) -> dict[str, Any]:
        note = store.add_note(_text_arg(args, "text"))
        await publish_changed(store, publish, "notes")
        return note

    async def notes_remove(args: dict[str, Any]) -> dict[str, Any]:
        note_id = _id_arg(args)
        if not store.remove_note(note_id):
            raise ValueError("unknown note id")
        await publish_changed(store, publish, "notes")
        return {"id": note_id, "removed": True}

    async def habits_checkin(args: dict[str, Any]) -> dict[str, Any]:
        habit_id = _id_arg(args)
        done = _optional_bool_arg(args, "done")
        habit = store.check_in(habit_id, done=True if done is None else done)
        if habit is None:
            raise ValueError("unknown habit id")
        await publish_changed(store, publish, "habits")
        return habit

    actions.register("tasks.add", tasks_add, "Add an open task with a title")
    actions.register("tasks.toggle", tasks_toggle, "Mark a task done or open again")
    actions.register("tasks.remove", tasks_remove, "Delete a task")
    actions.register("notes.add", notes_add, "Add a note with some text")
    actions.register("notes.remove", notes_remove, "Delete a note")
    actions.register("habits.checkin", habits_checkin, "Check in a habit for today")
