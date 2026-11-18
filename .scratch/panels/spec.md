# Panels

Direction (ADR 0002): Panels are the second pillar. Old devices the user owns become desk panels showing pages of widgets, served by the Brain over the same WebSocket protocol as the Body. Ideas come from PhoneBox (https://github.com/ersinkoc/phonebox); none of its code is used.

Target devices: RG406H (Android 13), Moto G5 (Android 7), an iPad and an old iPhone (Safari), an old laptop (browser), a Kindle (E-ink Mode). The ESP32 has not arrived; nothing here writes firmware, but protocol changes must stay ESP32-friendly (small JSON, no browser-only assumptions).

## Execution rule (spec-then-code gate)

- Every issue below has been grilled. Coding happens in subagents, never in the planning session.
- An issue is **done** when its acceptance criteria hold, all tests pass (`.venv/bin/python -m pytest -q`, `node --test tests/frontend/*.test.cjs`), a reviewer agent approved it, and the restarted server was checked live.
- Daily use comes after and feeds new issues; it does not block.
- Issues may run in parallel when their files don't overlap. P01 and P02 are the foundation and land first.
- Built with **nested subagents** (Opus orchestrator → Sonnet leads → Haiku coders) sharing `.scratch/agents/board.md`. Every task is logged in `.scratch/agents/ledger.md`.

## Security baseline (applies to every issue)

- The LAN is trusted (ADR 0002): Panels connect without the access token. The Mac editor is opened on the Mac; devices never receive credentials.
- Devices send **action IDs**, never commands. Every Mac effect goes through the existing whitelists in `app/mac_control.py` (`subprocess.run` with an argv list, never `shell=True`).
- Credentials for data sources live in `.env` on the Mac, are never sent to devices, and are masked in logs.
- Calendar, email and file contents follow Data Consent before reaching an LLM.

## Issues

| # | Issue | Depends on | Status |
|---|-------|-----------|--------|
| P01 | Device Roles and protocol extension | — | done (RG406H test pending) |
| P02 | Panel web runtime, Layouts and widget framework | P01 | in-progress |
| P03 | Mac Layout editor | P02 | ready-for-agent |
| P04 | Android kiosk shell for old devices | P01 | ready-for-agent |
| P05 | E-ink Mode (Kindle) | P02 | ready-for-agent |
| P06 | Signals | P01 | done |
| P07 | Widgets: Everyday | P02, P06 | ready-for-agent |
| P08 | Widgets: Mac monitoring | P02 | ready-for-agent |
| P09 | Widgets: AI coding | P02, P06 | ready-for-agent |
| P10 | Widgets: Control Deck and Automation | P02, P06 | ready-for-agent |

Lupin issue 05 (tasks, notes, habits) owns the store behind the notes, checklist and habit widgets in P07. Lupin issue 08 (image editor) is a widget built on P02.
