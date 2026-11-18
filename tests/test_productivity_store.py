"""Tests for the productivity store: tasks, notes, habits, streaks and due reminders."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from app.productivity.store import ProductivityStore

# 2026-11-18 is a Wednesday.
NOW = datetime(2026, 11, 18, 9, 0, 0)


class FakeClock:
    """Mutable clock: set `now` to move time; calling it returns the current value."""

    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock(NOW)


@pytest.fixture
def store(tmp_path: Path, clock: FakeClock):
    productivity = ProductivityStore(tmp_path / "productivity.db", clock=clock)
    yield productivity
    productivity.close()


# ------------------------------------------------------------------ tasks


def test_add_list_done_and_remove_task(store: ProductivityStore, clock: FakeClock) -> None:
    task = store.add_task("  Buy   milk ")
    assert task["title"] == "Buy milk"
    assert task["done"] is False
    assert task["done_at"] is None
    assert task["created_at"] == "2026-11-18T09:00:00"

    second = store.add_task("Call mom")
    assert [t["id"] for t in store.list_tasks()] == [task["id"], second["id"]]

    clock.now = datetime(2026, 11, 18, 10, 30, 0)
    done = store.set_task_done(task["id"])
    assert done is not None
    assert done["done"] is True
    assert done["done_at"] == "2026-11-18T10:30:00"
    assert [t["id"] for t in store.list_tasks()] == [second["id"]]
    assert [t["id"] for t in store.list_tasks(include_done=True)] == [task["id"], second["id"]]

    reopened = store.set_task_done(task["id"], done=False)
    assert reopened is not None
    assert reopened["done"] is False
    assert reopened["done_at"] is None

    assert store.set_task_done(9999) is None
    assert store.remove_task(second["id"]) is True
    assert store.remove_task(second["id"]) is False


def test_find_tasks_is_case_and_accent_insensitive(store: ProductivityStore) -> None:
    store.add_task("Buy café beans")
    store.add_task("Water plants")

    assert [t["title"] for t in store.find_tasks("cafe")] == ["Buy café beans"]
    assert [t["title"] for t in store.find_tasks("CAFÉ")] == ["Buy café beans"]
    assert store.find_tasks("") == []
    assert store.find_tasks("   ") == []


def test_find_tasks_respects_done_filter(store: ProductivityStore) -> None:
    task = store.add_task("Cafe run")
    store.set_task_done(task["id"])

    assert store.find_tasks("cafe") == []
    assert [t["id"] for t in store.find_tasks("cafe", include_done=True)] == [task["id"]]


def test_task_validation(store: ProductivityStore) -> None:
    with pytest.raises(ValueError):
        store.add_task("   ")
    with pytest.raises(ValueError):
        store.add_task("x" * 201)
    with pytest.raises(ValueError):
        store.add_task(42)  # type: ignore[arg-type]
    assert store.add_task("x" * 200)["title"] == "x" * 200


# ------------------------------------------------------------------ notes


def test_notes_add_list_find_and_remove(store: ProductivityStore, clock: FakeClock) -> None:
    first = store.add_note("  remember the charger  ")
    assert first["text"] == "remember the charger"
    assert first["created_at"] == "2026-11-18T09:00:00"

    clock.now = datetime(2026, 11, 18, 11, 0, 0)
    second = store.add_note("buy cafe filters")

    assert [n["id"] for n in store.list_notes()] == [second["id"], first["id"]]
    assert [n["text"] for n in store.find_notes("CAFE")] == ["buy cafe filters"]
    assert store.find_notes("") == []

    assert store.remove_note(first["id"]) is True
    assert store.remove_note(first["id"]) is False
    assert [n["id"] for n in store.list_notes()] == [second["id"]]


def test_list_notes_limit(store: ProductivityStore) -> None:
    for text in ("one", "two", "three"):
        store.add_note(text)

    assert [n["text"] for n in store.list_notes(limit=2)] == ["three", "two"]
    with pytest.raises(ValueError):
        store.list_notes(limit=0)


def test_note_validation(store: ProductivityStore) -> None:
    with pytest.raises(ValueError):
        store.add_note("")
    with pytest.raises(ValueError):
        store.add_note("   ")
    with pytest.raises(ValueError):
        store.add_note("n" * 2001)
    assert len(store.add_note("n" * 2000)["text"]) == 2000


# ----------------------------------------------------------------- habits


def test_add_habit_validation_and_defaults(store: ProductivityStore) -> None:
    with pytest.raises(ValueError):
        store.add_habit("")
    with pytest.raises(ValueError):
        store.add_habit("x" * 81)
    with pytest.raises(ValueError):
        store.add_habit("Stretch", days=[7])
    with pytest.raises(ValueError):
        store.add_habit("Stretch", days=[True])
    with pytest.raises(ValueError):
        store.add_habit("Stretch", time="24:00")
    with pytest.raises(ValueError):
        store.add_habit("Stretch", time="9:00")

    habit = store.add_habit("Stretch", days=[4, 0, 4], time="07:15")
    assert habit["days"] == [0, 4]
    assert habit["time"] == "07:15"
    assert habit["streak"] == 0
    assert habit["done_today"] is False

    every_day = store.add_habit("Water", days=[])
    assert every_day["days"] == []
    assert every_day["time"] is None


def test_get_and_find_habits(store: ProductivityStore) -> None:
    habit = store.add_habit("Meditação")
    store.add_habit("Read")

    assert store.get_habit(habit["id"])["name"] == "Meditação"
    assert store.get_habit(9999) is None
    assert [h["id"] for h in store.find_habits("meditacao")] == [habit["id"]]
    assert len(store.list_habits()) == 2


def test_daily_streak_counts_consecutive_days(store: ProductivityStore) -> None:
    habit = store.add_habit("Read")
    for day in ("2026-11-16", "2026-11-17", "2026-11-18"):
        store.check_in(habit["id"], day=day)

    got = store.get_habit(habit["id"])
    assert got is not None
    assert got["streak"] == 3
    assert got["done_today"] is True


def test_skipped_day_resets_streak(store: ProductivityStore) -> None:
    habit = store.add_habit("Read")
    store.check_in(habit["id"], day="2026-11-18")
    store.check_in(habit["id"], day="2026-11-16")  # 2026-11-17 missed

    assert store.get_habit(habit["id"])["streak"] == 1


def test_unchecked_today_keeps_yesterdays_streak(store: ProductivityStore) -> None:
    habit = store.add_habit("Read")
    store.check_in(habit["id"], day="2026-11-16")
    store.check_in(habit["id"], day="2026-11-17")

    got = store.get_habit(habit["id"])
    assert got["done_today"] is False
    assert got["streak"] == 2

    store.check_in(habit["id"])  # check in today
    got = store.get_habit(habit["id"])
    assert got["done_today"] is True
    assert got["streak"] == 3


def test_weekday_habit_streak_skips_unscheduled_days(store: ProductivityStore) -> None:
    habit = store.add_habit("Gym", days=[0, 2, 4])  # Monday, Wednesday, Friday
    # Mon 11-09, Wed 11-11, Fri 11-13, Mon 11-16, Wed 11-18 (today).
    for day in ("2026-11-09", "2026-11-11", "2026-11-13", "2026-11-16", "2026-11-18"):
        store.check_in(habit["id"], day=day)

    assert store.get_habit(habit["id"])["streak"] == 5


def test_weekday_habit_unchecked_today_keeps_streak(store: ProductivityStore) -> None:
    habit = store.add_habit("Gym", days=[0, 2, 4])
    for day in ("2026-11-11", "2026-11-13", "2026-11-16"):
        store.check_in(habit["id"], day=day)

    got = store.get_habit(habit["id"])
    assert got["done_today"] is False
    assert got["streak"] == 3


def test_check_in_undo_and_unknown_habit(store: ProductivityStore) -> None:
    habit = store.add_habit("Read")
    checked = store.check_in(habit["id"])
    assert checked["done_today"] is True

    undone = store.check_in(habit["id"], done=False)
    assert undone["done_today"] is False
    assert undone["streak"] == 0

    assert store.check_in(9999) is None


def test_check_in_rejects_invalid_day(store: ProductivityStore) -> None:
    habit = store.add_habit("Read")
    with pytest.raises(ValueError):
        store.check_in(habit["id"], day="2026-13-01")
    with pytest.raises(ValueError):
        store.check_in(habit["id"], day="18/11/2026")


def test_due_habits_time_and_check_in(store: ProductivityStore, clock: FakeClock) -> None:
    habit = store.add_habit("Stretch", time="09:00")

    clock.now = datetime(2026, 11, 18, 8, 59, 0)
    assert store.due_habits() == []

    clock.now = datetime(2026, 11, 18, 9, 30, 0)
    assert [h["id"] for h in store.due_habits()] == [habit["id"]]

    store.check_in(habit["id"])
    assert store.due_habits() == []


def test_due_habits_after_mark_notified_and_next_day(
    store: ProductivityStore, clock: FakeClock
) -> None:
    habit = store.add_habit("Water", time="09:00")
    clock.now = datetime(2026, 11, 18, 9, 30, 0)
    assert [h["id"] for h in store.due_habits()] == [habit["id"]]

    assert store.mark_habit_notified(habit["id"], "2026-11-18") is True
    assert store.due_habits() == []

    clock.now = datetime(2026, 11, 19, 9, 30, 0)
    assert [h["id"] for h in store.due_habits()] == [habit["id"]]


def test_due_habits_accepts_explicit_now(store: ProductivityStore) -> None:
    habit = store.add_habit("Stretch", time="18:00")
    assert store.due_habits(now=datetime(2026, 11, 18, 17, 59)) == []
    assert [h["id"] for h in store.due_habits(now=datetime(2026, 11, 18, 18, 0))] == [habit["id"]]


def test_due_habits_wrong_weekday_and_no_time(
    store: ProductivityStore, clock: FakeClock
) -> None:
    store.add_habit("Review", days=[0], time="09:00")  # Mondays only
    store.add_habit("Journal", time=None)  # never due without a time

    clock.now = datetime(2026, 11, 18, 23, 59, 0)  # Wednesday
    assert store.due_habits() == []

    clock.now = datetime(2026, 11, 16, 9, 0, 0)  # Monday
    assert [h["name"] for h in store.due_habits()] == ["Review"]


def test_remove_habit_deletes_habit_and_checkins(store: ProductivityStore) -> None:
    habit = store.add_habit("Read")
    store.check_in(habit["id"], day="2026-11-18")

    assert store.remove_habit(habit["id"]) is True
    assert store.get_habit(habit["id"]) is None
    assert store.remove_habit(habit["id"]) is False

    remaining = store._conn.execute("SELECT COUNT(*) FROM habit_checkins").fetchone()[0]
    assert remaining == 0


# ------------------------------------------------------------ persistence


def test_data_persists_across_reopening(tmp_path: Path, clock: FakeClock) -> None:
    path = tmp_path / "productivity.db"

    first = ProductivityStore(path, clock=clock)
    first.add_task("Persist me")
    first.add_note("still here")
    habit = first.add_habit("Read", days=[1], time="08:00")  # Tuesdays
    first.check_in(habit["id"], day="2026-11-17")  # Tuesday
    first.close()

    second = ProductivityStore(path, clock=clock)
    try:
        assert [t["title"] for t in second.list_tasks()] == ["Persist me"]
        assert [n["text"] for n in second.list_notes()] == ["still here"]
        got = second.get_habit(habit["id"])
        assert got is not None
        assert got["days"] == [1]
        assert got["time"] == "08:00"
        # Today (Wednesday) is unscheduled, so the streak starts at last Tuesday.
        assert got["streak"] == 1
    finally:
        second.close()
