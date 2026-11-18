# P03 - Mac Layout editor

Status: ready-for-agent
Blocked by: P02

## Scope

- A browser editor served by the Brain, used on the Mac (like PhoneBox's settings page).
- Devices list: name, last seen, role(s), Body priority order (drag to reorder), assigned Layout.
- Layouts: create from a template, rename, duplicate, delete; pages; drag and resize widgets on the 12 × 6 grid; portrait/landscape variants; per-widget settings and data source configuration.
- Live preview at a chosen device's size, with live data.
- Credentials typed here are written to `.env` on the Mac and never shown back in full.
- Templates to start with: Home, System, AI coding, Music, Planner, Control Deck (contents filled as widget issues land).

## Acceptance criteria

- [ ] A Layout built in the editor shows on an assigned device after Save, without restarting it.
- [ ] Two devices can share a Layout; changing it updates both.
- [ ] Device roles and Body priority are editable here (P01 storage).
- [ ] No credential is ever sent to a device or written to logs.
