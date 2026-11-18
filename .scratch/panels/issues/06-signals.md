# P06 - Signals

Status: in-progress (approved; review follow-ups being fixed)
Blocked by: P01

## Scope

- A Brain-side event bus: data sources emit Signals `{kind, source, importance, summary, data}`; subscribers are Panels (widgets), Lupin (Expression/Mood/speech) and the MCP server (lupin-foco 12).
- Importance levels. Lupin speaks unprompted only for the important set: Claude Code needs the user, build/CI failed, timer done, habit due, meeting soon. Everything else at most changes his Expression.
- Focus rule: during a Pomodoro, Lupin stays quiet except for "Claude Code needs the user".
- Rate limit per kind so Lupin never repeats himself.
- Signals carrying calendar, email or file contents follow Data Consent before any of it reaches an LLM.

## Acceptance criteria

- [ ] A test source can emit Signals that reach a subscribed widget and Lupin.
- [ ] Unimportant Signals never make Lupin speak.
- [ ] During a Pomodoro only "Claude Code needs the user" makes him speak.
- [ ] Rate limits are covered by tests.
