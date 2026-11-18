# 05 - Tasks, notes and habits by voice

Status: ready-for-agent

## Context

Inspired by Taby (focus and habits): Lupin helps capture tasks, notes and habits by speaking, as an Action in the conversation. Comes after 04.

## Scope

- Create and query tasks, notes and habits by voice (tap-to-talk, listening on the Mac's microphone).
- Lupin confirms by voice what he recorded.
- Define where the data lives and how it relates to Cowork.

## Acceptance criteria

- [ ] The exact scope (what is a task, a note and a habit) and the storage are defined.
- [ ] Decided whether writing to Cowork is allowed, since Cowork is read-only after 01.
- [ ] Voice capture works end to end with spoken confirmation.
- [ ] 1 week of real use (min. 4 days) without an irritating bug.

## Open questions

- Where does the data live, if Cowork is read-only?
- Do habit reminders belong to this issue or to Presence?

## Decisions (grill 2026-11-18)

- Tasks, notes and habits live in the Brain's sqlite. Cowork stays read-only.
- The same store backs the notes, checklist and habit widgets (panels P07): ticking on a Panel and asking Lupin by voice see the same items.
- This issue owns habits and their schedules. A due habit emits a Signal (panels P06); Lupin mentions it under the "important only, respects focus" rule; the habit widget shows streaks.
- Lupin confirms by voice what he recorded.
