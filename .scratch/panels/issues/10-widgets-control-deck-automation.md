# P10 - Widgets: Control Deck and Automation

Status: ready-for-agent
Blocked by: P02, P06

## Scope

- Control Deck: system volume and mute, microphone mute, media keys, per-app audio where macOS allows, OBS (obs-websocket, credentials on the Mac), macros that extend Shortcuts (sequences of existing whitelisted Shortcut steps).
- The Dock page (Pinned Shortcuts, open apps) becomes a widget group usable on any Layout.
- Automation: incoming webhooks that set widget values or emit Signals (local endpoint, a per-webhook random path), Home Assistant entities (URL + token on the Mac), simple rules ("when app X is in front, switch the Panel to page Y").
- Every control is an action ID resolved on the Brain; no command text from devices.

## Acceptance criteria

- [ ] Volume, mic mute and media controls work from a Panel.
- [ ] A macro runs only whitelisted steps.
- [ ] A webhook can update a widget and emit a Signal.
- [ ] Home Assistant and OBS work when configured and hide cleanly when not.
