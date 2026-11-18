# P05 - E-ink Mode (Kindle)

Status: done (device test pending)
Blocked by: P02

## Scope

- A server-rendered page for e-ink devices: black and white, large type, no animation, no WebSocket; refresh every N minutes (default 5) by a meta refresh or minimal JS.
- Uses the device's Layout but only widgets that declare an e-ink render (clock, Today, calendar, weather, notes/tasks, a line from Lupin).
- Works in the Kindle's experimental browser: no modern JS required.
- The Kindle is view-only: no actions.

## Acceptance criteria

- [ ] The Kindle shows its Layout and refreshes on schedule without user input.
- [ ] Widgets without an e-ink render are skipped with no broken layout.
