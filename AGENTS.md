# Desk Assistant — Agent Instructions

This file is for every coding agent that works on this project (Claude, Gemini, Codex…). Read it before doing anything.

You are working inside the repository root (the directory that holds this file).

## Read first

1. `docs/adr/0001-companion-first-brain-and-body.md`: the product direction ("a desk companion that actually works", one feature at a time).
2. `GLOSSARY.md`: the domain language. Use its terms.
3. `docs/adr/0002-two-pillars-lupin-and-panels.md`: two pillars (Lupin and Panels), Device Roles, LAN trust, and the spec-then-code gate.
4. `.scratch/lupin-foco/spec.md` and `.scratch/panels/spec.md`: the issue lists and the execution rules.
5. `.scratch/agents/board.md`: who is working on which files right now. Read it before a task and update it after.

The older swarm-era design that lived in `docs/superpowers/` was superseded by ADR 0001 and removed from the tree (it is still in git history). Do not follow it.

## Project rules

- **Workspace**: don't modify other directories (such as `nathan-os-app` or `Cowork`). Work only inside this repository.
- **Git**: work on the current feature branch, never push, and never touch `main` unless the user asks. Commit only the files you changed.
- **Security and least privilege**:
  - Never commit `.env`, `certs/`, `.venv/` or `data/*.db*`.
  - Never expose `LLM_API_KEY` in logs, HTTP/WS responses or tests.
  - macOS execution (`app/mac_control.py`) must only use `subprocess.run` with an `argv` list and a strict whitelist: never `shell=True`, and never arbitrary commands coming from a client.
  - Calendar and email are read-only. They reach an LLM provider only through the user's Data Consent (see `GLOSSARY.md`). Without it, no calendar or email data leaves the Mac.
- **Language**:
  - Code, comments, identifiers, UI text, commits, docs, issues and `README.md` are in **English**. Older code and docs still in Brazilian Portuguese are being migrated; don't add new Portuguese.
  - What Lupin **says** to the user (his voice, First Wake, the system prompt's reply language) follows a user setting, Brazilian Portuguese by default.
- **Platforms**: keep native compatibility with the **Anbernic RG406H** (Android 13, 960×720, Gamepad API) and **macOS**. Panels must also run on old devices: the **Moto G5** (Android 7, WebView shell with minSdk 24), an **iPad/iPhone** (Safari, `safe-area-inset-*`; supported as Panels, best-effort as Bodies), an old laptop's browser, and a **Kindle** (E-ink Mode, no modern JS).
- **Python environment**: always use `.venv/bin/python` and `.venv/bin/pytest` (or `uv`).
  - Python tests: `.venv/bin/python -m pytest -q`.
  - Frontend tests: `node --test tests/frontend/*.test.cjs`.
- **Connected device**: the RG406H may be connected over ADB (`RG406H01980952`), with `adb reverse` and `RECORD_AUDIO` granted to Chrome.
- **Verification**: work counts as done only after all tests pass and the updated server has been restarted for a live check.
- **Parallel agents**: if several agents build at once, split the files so no two agents touch the same file. Claim files in `.scratch/agents/board.md`; log finished tasks in `.scratch/agents/ledger.md`.
- **Decide here, code elsewhere** (ADR 0002): planning, grilling, specs and orchestration run on Opus and write no feature code. Code is written by Sonnet leads and Haiku coders, from a grilled spec. Never make product decisions while coding; ask.

## Agent skills

### Issue tracker

Issues and specs are tracked as local markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the five default canonical triage roles (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout (`GLOSSARY.md` and `docs/adr/` at the repo root). See `docs/agents/domain.md`.
