# P09 - Widgets: AI coding

Status: ready-for-agent
Blocked by: P02, P06

## Scope

- **Claude Code sessions**: list of local sessions (project, model, status, duration, tokens) read from `~/.claude/projects` transcripts.
- **Permission prompts**: opt-in. A setup button on the Mac adds Claude Code hooks (permission request, notification, stop) that POST to the Brain on localhost. A prompt shows on Panels with **Allow** / **Deny**; the answer flows back through the hook; a timeout falls back to Claude Code's own prompt. Emits the "Claude Code needs the user" Signal. The setup shows exactly what it adds and can remove it.
- Codex sessions where the CLI exposes data.
- Quotas and reset times for Claude/Codex, with a burn-rate forecast, where the data is available locally.
- GitHub: review requests and CI status through the `gh` CLI login (no new token).
- Never log prompt contents or tool arguments beyond what the widget shows; never expose tokens.

## Acceptance criteria

- [ ] With hooks installed, a Claude Code permission prompt appears on a Panel and Allow/Deny resolves it.
- [ ] Removing the hooks from the Mac restores Claude Code's original settings exactly.
- [ ] A failing CI run emits a Signal and Lupin mentions it once.

## Security note

The LAN is trusted (ADR 0002), so any device on the Wi-Fi can press Allow. The ADR records this risk; do not add pairing in this issue.
