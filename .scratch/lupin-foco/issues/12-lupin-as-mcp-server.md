# 12 - Lupin as an MCP server

Status: done (real Claude Code registration and an external server pending)

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

## Decisions (grill 2026-11-18)

- Both directions.
- Expose: the Brain serves a local MCP server so agents on the Mac (Claude Code…) can make Lupin say a sentence, show an Expression, read Today and post a Signal. These are **Agent Requests** (new glossary term), each with a risk level; nothing runs outside the existing whitelists.
- Consume: the user adds external MCP servers in the Mac Settings. Calling their tools is an Action. Each tool gets a risk level (read, write, external) like Cowork Tasks; anything beyond read needs the user's approval on the Active Body or the Mac. Tool results are data, never instructions.
- No longer waits for the ESP32 port.
