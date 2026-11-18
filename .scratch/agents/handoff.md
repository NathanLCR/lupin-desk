# Handoff: orchestrating the 2026-11-18 push

Read this first if you are the orchestrator session. Then read `AGENTS.md`, `docs/adr/0002-two-pillars-lupin-and-panels.md`, `GLOSSARY.md`, `.scratch/panels/spec.md` and `.scratch/lupin-foco/spec.md`. Every issue listed as `ready-for-agent` has been grilled; its file (with a *Decisions* section for lupin-foco issues) is the spec. **Don't re-decide anything; if a spec is ambiguous, ask the user.**

Soft deadline: as much as possible by Thursday 2026-11-19. Not a hard rule.

## 0. Before anything

1. The app must have been restarted after 2026-11-18 so `ANTHROPIC_DEFAULT_HAIKU_MODEL=claude-haiku-5-5` is loaded. Check: spawn one tiny Agent with `model: "haiku"` that replies "ok". If it fails with `model_not_found`, tell the user and stop the Haiku layer (Sonnet does the coding).
2. Agent teams need `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` (env or `env` in settings). Changing settings needs the user's yes; ask once.
3. Branch: stay on `lupin-foco`. Never push, never touch `main`.

## 1. Roles

- **Orchestrator (you, Opus)**: plans, assigns, owns shared files, merges, verifies, keeps the board, writes the report. Writes **no feature code**.
- **Sonnet leads** (Agent tool, `model: "sonnet"`, a type with the Agent tool, e.g. `general-purpose`): one per issue. Break the issue into small tasks, claim files on the board, spawn Haiku coders, review their diffs, run the tests, commit their own files, log the ledger.
- **Haiku coders** (spawned by a lead with `model: "haiku"`): one small, well-specified task each (one module or one test file). Nesting is supported up to 3 levels.
- **Reviewer**: before an issue is marked done, a fresh Sonnet agent reviews the diff against the issue's acceptance criteria and `AGENTS.md` security rules.

## 2. Two mechanisms (the experiment)

- **Panels track = nested subagents** (Opus → Sonnet lead → Haiku coders), coordinating through `.scratch/agents/board.md`.
- **Lupin track = agent team** (experimental): teammates for 04, 05, 06, 07, 08, 11, 12, messaging each other and sharing the team task list. They also read and update the board, since the two tracks share the repo.
- **Baseline**: issue 07 (Dictation) is also built by one Sonnet agent alone, with `isolation: "worktree"`. Compare the two versions; merge only the better one and say why in the report.

## 3. Order and file conflicts

- **Foundation first**: P01 (Device Roles + protocol) and P06 (Signals) land before P02–P10 and before lupin-foco 04, 05, 08.
- The Lupin team can start immediately with work that doesn't need them: 11 (Ollama provider, Kokoro TTS), 07, 12, 06.
- Then P02 → (P03, P04, P05, P07, P08, P09, P10 in parallel by files) and lupin-foco 04, 05, then 08 on top of P02.
- `app/main.py` (1,790 lines) is the hot spot. Only the orchestrator edits it, to register new routers/modules. Features go in new modules.
- P07's notes/checklist/habit widgets use the store from lupin-foco 05; agree the API on the board before both start.

## 4. Done means

Acceptance criteria hold; `.venv/bin/python -m pytest -q` and `node --test tests/frontend/*.test.cjs` pass; reviewer approved; the server was restarted and checked live (RG406H over ADB `RG406H01980952` when relevant). Then set the issue's `Status:` to `done` and update the spec table.

## 5. Security reminders (from AGENTS.md and ADR 0002)

- Never commit `.env`, `certs/`, `.venv/`, `data/*.db*`. Never log or return `LLM_API_KEY` or data-source tokens.
- `app/mac_control.py`: `subprocess.run` with an argv list and a strict whitelist only; devices send action IDs, never commands.
- Calendar, email and file contents reach an LLM only with Data Consent.
- The LAN is trusted by the user's choice; don't add pairing, but don't widen anything else either.
- Claude Code hooks are opt-in, installed only from an explicit Mac setup button, and fully removable.

## 6. The report

When the push ends (or by Thursday evening), write `docs/agent-workflow-report.md` from `ledger.md`:
- Tokens, wall time, fix-ups and test results per mechanism (nested vs team vs baseline on issue 07).
- Quality notes from the reviewers: bloat, consistency, bugs found later.
- What broke in the coordination (file conflicts, idle agents, context loss).
- Verdict: which setup to reuse, and when.

If a setup clearly wins, turn it into a reusable skill (with the user's OK) so it can run in other projects.
