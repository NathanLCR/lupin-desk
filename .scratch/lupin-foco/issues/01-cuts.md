# 01 - Cuts

Status: done

## Context

Desk Assistant grew too wide (ADR 0001). Before any new feature, we cut whatever isn't in daily use. The removed code lives only on the `snapshot/swarm-2026-11-16` branch.

## Scope

- Remove Ambient Display as its own Mode: the clock, Pomodoro and Now Playing now sit around Lupin in Pet Mode.
- Skills and Diagnostics stop being Modes and move to a Settings area.
- Cowork becomes read-only: remove write/external Cowork Tasks, the diff preview and the approval runner, in the UI and in the prompt.
- Remove Screen Look and Clipboard Read (formerly "Jarvis"); the name "Jarvis" must disappear from the code, the UI and the prompts.
- Freeze the Electron mini-pet: no new work.
- The iPhone gets no dedicated work.
- Keep everything that Pet Mode, Dock, Today (read-only) and First Wake use.

## Acceptance criteria

- [x] The RG406H has only two Modes: Pet and Dock.
- [x] Clock, Pomodoro and Now Playing appear in Pet Mode, around Lupin.
- [x] Skills and Diagnostics are reached through Settings, not through a Mode.
- [x] No write or external Cowork Task exists; no diff preview or approval runner; the prompt doesn't mention them.
- [x] Today keeps working by reading Cowork.
- [x] `grep -ri jarvis` finds nothing in the active code.
- [x] Screen Look and Clipboard Read no longer exist.
- [x] Electron mini-pet intact and marked as frozen.
- [x] Existing tests pass; the `snapshot/swarm-2026-11-16` branch still has the cut code.
