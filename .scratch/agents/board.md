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

## Decisions and notes

## Blockers
