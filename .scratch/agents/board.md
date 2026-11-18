# Agent board

Every agent (orchestrator, leads, coders, teammates) **reads this file before starting a task and updates it right after**. It is how agents see each other. Keep entries short; newest at the bottom of each section.

## Rules

- Claim a file in *File ownership* before editing it. Never edit a file another agent holds. If you need it, write under *Requests* and wait for the owner or the orchestrator.
- `app/main.py`, `app/config.py`, `GLOSSARY.md`, `docs/adr/*`, `AGENTS.md` and the spec files are **orchestrator-owned**: request changes, don't make them.
- Prefer new modules (for example `app/panels/…`, `app/signals.py`, `static/panel/…`) registered with one line in `app/main.py`, over growing `app/main.py`.
- Release your files when your task is done (delete your rows).
- Log every finished task in `ledger.md`.

## File ownership

| File or folder | Owner (agent / task) | Since |
|---|---|---|

## In progress

| Task | Issue | Track | Agent (model) | Started |
|---|---|---|---|---|

## Requests

- (all wave 1–3 patches applied: P01, P06, 05, P02, 12 and their fix-ups.)

## Decisions and notes

- 2026-11-18 (orchestrator): agent teams are not exposed in the desktop app, so the Lupin track also runs nested. The experiment is now nested vs the Sonnet-only baseline on 07.
- 2026-11-18 (orchestrator): for this push `static/app.js` and `static/index.html` are orchestrator-owned too. New frontend code goes in new `static/<feature>.js` files; request hookups via `.scratch/agents/patches/`.
- `listening` and `thinking` already exist as states in `static/lupin/expressions.json`; reuse them.
- Wave 2 (after P01): P06 Signals. Wave 3 (after P01+P06): P02, Lupin 05, 12. Lupin 06 after 05.
- Wave 4 (2026-11-18): P03 Mac Layout editor, P04 Android kiosk shell, P05 E-ink Mode, P07 Everyday widgets, Lupin 06 Smart search. Wave 5: P08, P09, P10, Lupin 04, Lupin 08.
- Wave 4 split: P05 owns the server-side e-ink renders (Python, under app/panels/); P07 widgets do NOT write e-ink renders. Grid size is data in the Layout JSON (portrait 6x12 vs 12x6 is still an open user question): never hardcode it.
- Open user questions: portrait grid 6x12 vs 12x6; should lupin_read_today (12) need Data Consent for Cowork tasks.

- 05 store API (lead-05; P07 widgets build on this). Store: `app/productivity/store.py` `ProductivityStore(db_path, clock=datetime.now)`, same sqlite file as memory.db (tables `tasks`, `notes`, `habits`, `habit_checkins`). Records are plain dicts:
  - task `{id, title, done, created_at, done_at}`; note `{id, text, created_at}`; habit `{id, name, days (weekday ints 0=Mon..6=Sun, [] = every day), time ("HH:MM" or null), created_at, streak, done_today}`.
  - Python: `add_task/list_tasks(include_done)/set_task_done(id, done)/find_tasks(q)/remove_task`; `add_note/list_notes(limit)/remove_note/find_notes`; `add_habit/list_habits/find_habits/check_in(id, day=None, done=True)/remove_habit/due_habits(now)/mark_habit_notified`.
  - REST (LAN-trusted, no Mac-only guard, so a Panel can tick): `GET/POST /api/tasks`, `PATCH/DELETE /api/tasks/{id}` (`{done}` / `{title}`); `GET/POST /api/notes`, `DELETE /api/notes/{id}`; `GET/POST /api/habits`, `POST /api/habits/{id}/checkin` (`{done: bool=true, day?: "YYYY-MM-DD"}`), `DELETE /api/habits/{id}`. Every GET returns `{"tasks": [...]}` / `{"notes": [...]}` / `{"habits": [...]}`; tasks GET takes `?include_done=true`.
  - Hub topics (widgets subscribe with `{"type":"subscribe","topics":["tasks"]}`): `tasks`, `notes`, `habits`; after ANY change (REST, action or voice) the full list payload above is published, same shape as GET. A due habit also arrives as signal kind `habit_due` on `signals` / `signal:habit_due` with `data {id, name, streak}`.
  - Panel Action IDs (P01 registry; args are a dict): `tasks.add {title}`, `tasks.toggle {id, done?}`, `tasks.remove {id}`, `notes.add {text}`, `notes.remove {id}`, `habits.checkin {id, done?}`. Each returns the updated record.
  - Brain wiring: `register(app, db_path)` in `app/productivity/__init__.py` sets `app.state.productivity` (store, `.start()`/`.stop()` for the habit scheduler, `.handle_voice(kind, target)`).

## Blockers

- Known pre-existing failure (not yours): `tests/frontend/minipet-state.test.cjs` "mini-pet applies the combined mute…" (string mismatch after the English translation; mini-pet is frozen). Treat the frontend suite as passing if this is the only failure. Don't fix it inside your issue.
- Pre-existing (follow-up, not yours): `SecretRedactingFilter` in app/config.py sets `record.args = None`, which crashes uvicorn's access-log formatter ("Logging error" spam in the server log).
- `.claude/` (agent worktrees) is untracked: never `git add` it.
