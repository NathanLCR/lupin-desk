# 12 - Lupin as an MCP server

Status: needs-triage

## Context

The Autonomous Lamp and xiaozhi-esp32 plug into the agent ecosystem through MCP (see `docs/market-research.md`). Lupin could expose a small MCP server so local agents can reach him. For example, Claude Code could have Lupin say "the build finished" in the Active Body.

## Scope (to be refined in triage)

- A minimal set of tools: say a sentence, show an Expression, maybe read Today.
- Local only. What authorises an agent, and what it is allowed to do, needs the same care as Cowork Tasks (risk levels, approval).
- Nothing an agent sends may run on the Mac outside the existing whitelists.

## Open questions

- Should Lupin expose MCP, consume MCP, or both?
- Is it an Action, or a new concept for the glossary?

Comes after the ESP32 port.
