# Lead brief (read this whole file before starting)

You are a **Sonnet lead** for one issue in `/Users/nathanlucio/Desktop/desk-assistant`, branch `lupin-foco`. The orchestrator (Opus) gave you the issue in your prompt.

## Read first

1. `AGENTS.md` (project rules, security, language, tests).
2. `GLOSSARY.md` (use its terms) and `docs/adr/0002-two-pillars-lupin-and-panels.md`.
3. Your issue file. Its *Decisions* section and scope are the spec. **Don't re-decide product questions.** If something is ambiguous, stop and write the question under *Blockers* in `.scratch/agents/board.md`, then end with the question in your final report.
4. `.scratch/agents/board.md`: see who owns which files.

## How you work

1. Explore only what you need. Write a short plan: 2–6 small tasks, each one module or one test file, with the exact files it touches.
2. Claim your files on the board (*File ownership*) before editing. Never edit a file another row owns.
3. Spawn **Haiku coders** with the Agent tool (`model: "haiku"`, `subagent_type: "general-purpose"`), one small, fully specified task each: file paths, function signatures, behaviour, the test to write, and the commands to run. Give them everything they need; they start cold. Coders run tests but never commit. Run independent coders in parallel only when their files don't overlap.
4. Review each coder's diff yourself. Fix small things directly, or send a precise follow-up. Count every follow-up round as a fix-up.
5. Run the full suites: `.venv/bin/python -m pytest -q` and `node --test tests/frontend/*.test.cjs`. Both must pass.
6. Commit **only your files** with a message in English (`feat: …` / `test: …`), ending with the line
   `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
   Never push. Never touch `main`. Never commit `.env`, `certs/`, `.venv/`, `data/*.db*`.
7. Release your rows on the board and add ledger rows (see below).

## Orchestrator-owned files (don't edit, request)

`app/main.py`, `app/config.py`, `static/app.js`, `static/index.html`, `GLOSSARY.md`, `docs/adr/*`, `AGENTS.md`, the spec and issue files.

- Put features in **new modules** (`app/<feature>.py`, `static/<feature>.js`) with a small `register(app, …)` or init function.
- For each change you need in an orchestrator-owned file, write a minimal unified diff to `.scratch/agents/patches/<issue>-<file>.diff` (for example `P01-main.py.diff`) and list it under *Requests* on the board. The orchestrator applies it. Write your tests so they pass **once the patch is applied**. Say in your final report which patches are pending.
- To test before the patch lands, you may apply it locally, run the tests, then revert it with `git checkout -- <file>`. Never commit an orchestrator-owned file.

## Security (from AGENTS.md and ADR 0002)

- `app/mac_control.py`: `subprocess.run` with an argv list and a strict whitelist only, never `shell=True`. Devices send action IDs, never commands.
- Never log or return `LLM_API_KEY` or data-source tokens.
- Calendar, email and file contents reach an LLM only with Data Consent.
- The LAN is trusted; don't add pairing, and don't widen anything else.
- Code, comments, UI text and commits in English. What Lupin says follows the language setting (pt-BR default), so spoken strings go through the existing speech tables (`app/speech_en.py`, `app/speech_pt_br.py`).

## Ledger (required)

Append one row per finished task to `.scratch/agents/ledger.md`. Every Agent result ends with a usage block (`subagent_tokens`, `tool_uses`, `duration_ms`): copy those numbers. Add one row for each Haiku coder task and one row for yourself (your own totals are filled in by the orchestrator; write `lead` and leave tokens as `?`).

`| <task> | <issue> | nested | haiku | <tokens> | <tool uses> | <wall time> | <pass/fail, +N tests> | <fix-up rounds> | <notes> |`

## Final report (keep it short, under 250 words)

- What was built, with the commit hash(es).
- Test results (counts) for both suites.
- Pending patches for orchestrator-owned files.
- Acceptance criteria: which hold, which need a live check on the device, which don't hold yet and why.
- Fix-up rounds per coder, and anything that broke in coordination.
