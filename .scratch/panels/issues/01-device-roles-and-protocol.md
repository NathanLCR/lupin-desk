# P01 - Device Roles and protocol extension

Status: done (live on Mac browser and RG406H 2026-11-18)

## Context

Each connected device gets a Device Role (Body, Panel, or Body + Panel). Lupin lives in one Active Body, chosen by a priority list the user sets on the Mac. Panels use the existing Body protocol WebSocket (issue 02 of lupin-foco), extended.

## Scope

- Device identity: a device generates a stable device ID on first run and sends it in its hello, with a human name and screen info (size, orientation, e-ink or not).
- The Brain stores devices (sqlite): ID, name, role(s), assigned Layout, last seen, priority rank among Bodies.
- Hello announces capabilities; the Brain answers with the device's role(s) and Layout ID. Roles are set on the Mac; a new device defaults to Panel.
- Active Body selection: highest-ranked connected Body by the user's priority list. Failover when it disconnects; Lupin's voice and Expression route to the new Active Body.
- Topic subscriptions: a device subscribes to the data topics of the widgets on its pages and receives small JSON pushes; unsubscribes on page change only if cheap (otherwise subscribe to the whole Layout).
- Actions by ID: `{"type":"action","id":"<action-id>","args":{...}}`. The Brain validates the ID against a registry; unknown IDs are rejected and logged without echoing arguments.
- LAN trust: Panels connect without `DESK_ACCESS_TOKEN` (ADR 0002). Keep the token code path for future use behind a setting; don't delete it.
- Update the protocol contract doc and tests.

## Acceptance criteria

- [ ] A device that connects for the first time appears on the Mac with a default Panel role.
- [ ] Changing a role or priority on the Mac takes effect without restarting the device.
- [ ] With two Body devices connected, Lupin is only in the highest-ranked one; disconnecting it moves him to the next.
- [ ] Panels receive only the topics they subscribed to.
- [ ] Unknown action IDs are rejected; no command string from a device ever reaches `mac_control`.
- [ ] Existing Body protocol tests still pass.

## Decisions

Per-device role choice; priority list for the Active Body; one protocol for all devices; trust the LAN.
