# Lupin and MCP

Lupin speaks MCP in both directions (issue 12). No extra Python package is needed: the protocol is implemented in `app/mcp_server.py` and `app/mcp_client.py`.

## Lupin as an MCP server (Agent Requests)

The Brain serves `POST /mcp` (MCP Streamable HTTP, JSON responses, no sessions). Agents on the Mac can ask Lupin to:

| Tool | Risk | What it does |
|---|---|---|
| `lupin_say` | write | Lupin says a sentence (max 280 chars) on the Active Body. Rate limited, silent during a Pomodoro. |
| `lupin_show_expression` | write | Shows one of the known Expressions. |
| `lupin_read_today` | read | Today's headline, top items and warnings (Cowork tasks and deadlines). Never calendar or e-mail. |
| `lupin_post_signal` | write | Posts a Signal. Only the kinds `claude_code_needs_user`, `build_failed`, `build_finished`, `agent_note`. The source is always `agent:<client>`; agents cannot attach data. |

Nothing here runs a command on the Mac. Everything goes through the Signals bus and Lupin's existing speech rules.

**Loopback only.** The rest of the app trusts the LAN (ADR 0002), but this server is for agents on the Mac: it refuses any peer that is not 127.0.0.1 or ::1, and any `Host` or `Origin` that is not localhost (DNS rebinding). Do not put a reverse proxy in front of it. Turn it off with `LUPIN_MCP_ENABLED=0`.

### Register it in Claude Code

Start the Brain, then:

```
claude mcp add --transport http lupin http://127.0.0.1:8000/mcp
```

(Use your Brain's port.) To label requests, add `--header "X-Lupin-Client: claude-code"`. Then ask Claude Code, for example, "tell Lupin the build finished". For a hook that pings Lupin when Claude Code needs you, call `lupin_post_signal` with kind `claude_code_needs_user`.

## External MCP servers (tools as Actions)

Settings > Skills, "External tools (MCP)" section (on the Mac) lists external servers. Add a stdio server (a command, run with an argv list, never a shell, with a minimal environment that does not include the Brain's keys) or an HTTP server (URL plus optional headers). Credentials are stored in `data/mcp_servers.json` (mode 600), are never sent to devices or logged, and are redacted from tool results.

Each tool has a risk level you set: `read` runs without asking; `write` and `external` (the default for every tool) ask for approval on the Active Body first. A server's own "read only" hint is ignored. Tool results are wrapped and labelled as untrusted data, and tool descriptions never enter the system prompt (only names and argument names do).
