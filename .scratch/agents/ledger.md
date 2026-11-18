# Workflow ledger

One row per finished task. Fill it from the agent's task-notification usage block (`subagent_tokens`, `tool_uses`, `duration_ms`). For agent teams, use `/usage` attribution and the transcripts under `~/.claude/projects/<project>/<session>/subagents/`.

- **Mechanism**: `nested` (Opus → Sonnet lead → Haiku coder), `team` (agent team), or `baseline` (Sonnet-only, issue 07).
- **Fix-ups**: how many review rounds the result needed before it passed (0 = right the first time).
- **Tests**: pass/fail at hand-off, plus count added.

| Task | Issue | Mechanism | Model | Tokens | Tool uses | Wall time | Tests | Fix-ups | Notes |
|---|---|---|---|---|---|---|---|---|---|
