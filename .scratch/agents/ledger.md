# Workflow ledger

One row per finished task. Fill it from the agent's task-notification usage block (`subagent_tokens`, `tool_uses`, `duration_ms`). For agent teams, use `/usage` attribution and the transcripts under `~/.claude/projects/<project>/<session>/subagents/`.

- **Mechanism**: `nested` (Opus → Sonnet lead → Haiku coder), `team` (agent team), or `baseline` (Sonnet-only, issue 07).
- **Fix-ups**: how many review rounds the result needed before it passed (0 = right the first time).
- **Tests**: pass/fail at hand-off, plus count added.

| Task | Issue | Mechanism | Model | Tokens | Tool uses | Wall time | Tests | Fix-ups | Notes |
|---|---|---|---|---|---|---|---|---|---|
| step-0 smoke test | — | nested | haiku | 68,991 | 1 | 4s | n/a | 0 | one-word reply; ~69k is the fixed per-subagent context overhead |
| team-spawn probe | — | (teams test) | haiku | 69,620 | 1 | 4s | n/a | 0 | team_name accepted but no team created; teams not exposed in the desktop app |
| baseline 07 (solo) | 07 | baseline | sonnet | 133,336 | 38 | 3m33s | py 158/158; fe 76/77 (minipet failure pre-existing), +tests in test_dictation.py and app.test.cjs | 2 (self-fixes) | commit 7e7592d on worktree branch; edits main.py/app.js directly; no live check yet |
| consent exception + slow notice | 11 | nested | haiku | 104,188 | 9 | 81s | pass, +12 tests | 0 (lead fixed round-trip reset) | |
| Kokoro TTS + say fallback | 11 | nested | haiku | 114,482 | 13 | 129s | pass, +22 tests | 0 | |
| local-mode frontend helper | 11 | nested | haiku | 88,728 | 10 | 32s | pass, +10 tests | 0 | |
| lead-11 | 11 | nested | sonnet | ? | ? | ? | pass | 0 | |
| dictation rules | 07 | nested | haiku | 106,984 | 5 | 112s | pass, +48 | 0 | app/dictation_rules.py |
| mac paste_text | 07 | nested | haiku | 118,254 | 9 | 49s | pass, +14 | 0 | clipboard paste + restore |
| dictation.js | 07 | nested | haiku | 115,153 | 9 | 127s | pass, +21 | 0 | tap-to-talk controller |
| dictation handler | 07 | nested | haiku | 99,457 | 11 | 108s | pass, +21 | 0 | app/dictation.py |
| lead-07 (dictation) | 07 | nested | sonnet | ? | ? | ? | pass, +1 ws (skipped until patch) | 0 | lead |
| lead 11 (own context) | 11 | nested | sonnet | 132,538 | 23 | 5m02s | py 277 pass (pre-patch); fe 85/86 | 0 | 3 Haiku coders, 0 fix-ups; one direct lead fix (consent reset); commit c123b7c; patches applied by orchestrator in next commit, suites green after (298 py, 125/126 fe) |
| lead 07 (own context) | 07 | nested | sonnet | 132,215 | 25 | 5m11s | py 298 pass +1 skip; fe pass except known minipet | 0 | 4 Haiku coders, 0 fix-ups; commit 5177aa4; patches pending (index.html conflicts with 11, trivial) |
| reviewer-07 (compare) | 07 | review | sonnet | 98,847 | 7 | 30s | nested 83 py/21 node; baseline 11 py/14 node | — | verdict: merge baseline; nested had 3 blocking issues (unapplied wiring, hardcoded strings, inline non-cancellable await); nested ~750 LOC + ~1,100 test LOC vs baseline ~270 + ~150 |
| reviewer-11 | 11 | review | sonnet | 96,735 | 7 | 60s | py 323 pass +1 skip | — | not approved: slow-notice timer leak (in orchestrator-applied patch), undefined name in kokoro_tts; patches committed as clutter |
| action registry | P01 | nested | haiku | 89,015 | 6 | 31s | pass, +20 | 0 | app/actions.py |
| device store | P01 | nested | haiku | 96,833 | 7 | 48s | pass, +14 | 0 | app/devices.py |
| device.js client identity | P01 | nested | haiku | 94,062 | 6 | 49s | pass, +19 (node) | 0 | static/device.js |
| device hub + routes | P01 | nested | haiku | 129,592 | 13 | 147s | pass, +25 | 0 | app/device_hub.py, device_routes.py |
| P01 lead (patches, integration tests, doc) | P01 | nested | sonnet | ? | ? | ? | pass, +5 (with patches) | 0 | lead |
| baseline 07 fix-up 1 | 07 | baseline | sonnet | 135,007 (cumulative, was 133,336) | 5 | 34s | py 159/159; fe 76/77 known | 1 | restore in finally + test; commit 8edc8f5. Note: subagent_tokens looks like the final context size, not total consumed |
| lead P01 (own context) | P01 | nested | sonnet | 138,195 | 26 | 9m42s | py 329 with patches (scratch worktree); fe pass except known | 0 | 4 Haiku coders, 0 fix-ups; commit 5876713; 5 wiring patches; flagged default-role gap -> user chose "Bodies keep Body" (fix-up round 1 in progress) |
| lead 11 fix-up 1 | 11 | nested | sonnet | 145,442 (cumulative) | 11 | 1m42s | +3 tests; timer error-path test fails without patch | 1 | commit 26846d8 + orchestrator applied 11-fix-main.py.diff (9173cc5); reviewer conditions met, approved without a 2nd review |
| merge baseline 07 | 07 | baseline | — | — | — | — | py 255 pass (5 P01 tests wait on wiring); fe 105/106 known | — | merge 3223ef2, no conflicts |
| lead P01 fix-up 1 (Bodies keep Body) | P01 | nested | sonnet | 147,736 (cumulative) | 11 | 1m38s | py 262 with patches | 1 | lead did it directly (no coder); commit 3f78170; orchestrator applied 5 patches cleanly |
| Signals bus + tests + speech lines | P06 | nested | haiku | 112,457 | 11 | 2m02s | pass, +15 tests | 0 | app/signals.py; lead added ActiveBodySpeaker, MacController.pomodoro_active, +2 tests |
| lead P06 (own context) | P06 | nested | sonnet | ? | ? | ? | py 279 with patch; fe see report | 0 | 1 Haiku coder; 1 commit; 1 main.py patch |
| reviewer-p01 | P01 | review | sonnet | 99,243 | 9 | 1m04s | py 262 | — | APPROVED, no blockers; nits: committed patch clutter, import order |
| lead P06 (own context) | P06 | nested | sonnet | 116,182 | 19 | 4m17s | py 279 with patch; fe 105/106 known | 0 | 1 Haiku coder, 0 fix-ups; lead wrote ActiveBodySpeaker + pomodoro_active itself; commit e2e7df4 |
| reviewer-p06 | P06 | review | sonnet | 91,912 | 8 | 56s | py 279; fe 105/106 known | — | APPROVED; 3 non-blocking follow-ups (signal notice unhandled in app.js, audio sentence-0 collision, sequential emit + rate race) |
| lead P06 fix-up 1 | P06 | nested | sonnet | ? | ? | ? | +5 py, +5 fe | 1 | signal audio keys, rate slot reservation, timeouts, no-active-body, static/signals.js |
| lead P06 fix-up 1 | P06 | nested | sonnet | 135,856 (cumulative) | 10 | 1m40s | py 284 (+5); fe 110/111 known | 1 | 3 review items fixed directly; commit d27a04a; 2 frontend patches applied |
| productivity store | 05 | nested | haiku | 112,421 | 8 | 99s | pass, +22 | 0 | app/productivity/store.py |
| voice handler + speech + prompt | 05 | nested | haiku | 128,681 | 17 | 176s | pass, +57 | 0 | voice.py, topics.py, speech tables, llm regex |
| habit scheduler | 05 | nested | haiku | 101,139 | 6 | 42s | pass, +10 | 0 | scheduler.py |
| routes + register + Panel actions | 05 | nested | haiku | 124,430 | 14 | 134s | pass, +14 | 0 | routes.py, __init__.py |
| lead 05 | 05 | nested | sonnet | 139,711 | 19 | 10m10s | py 538 with patch; fe known minipet only | 0 | lead; +1 ws test, main.py patch |
| Layout store + REST + templates | P02 | nested | haiku | 151,806 | 16 | 4m54s | pass, +52 py | 0 | app/panels/* |
| grid, arrange model, registry | P02 | nested | haiku | 129,335 | 19 | 2m51s | pass, +70 node | 0 | |
| widgets, pet, index.html, css | P02 | nested | haiku | 123,408 | 11 | 2m15s | pass, +18 node | 0 | |
| runtime.js | P02 | nested | haiku | 186,970 | 7 | 6m15s | pass, +24 node | 0 | stubs only; lead added real-module integration test |
| arrange-ui.js | P02 | nested | haiku | 153,718 | 9 | 4m14s | pass, +24 node | 0 | |
| lead P02 | P02 | nested | sonnet | 151,077 | 32 | 13m47s | py 565 pass +1 skip; fe 268/269 (known minipet) | 0 | lead |
| MCP server (Expose) + tests | 12 | nested | haiku | 125,736 | 15 | 2m46s | pass, +44 tests | 0 | app/agent_requests.py, app/mcp_server.py |
| MCP client + store + tests | 12 | nested | haiku | 136,510 | 8 | 4m24s | pass, +54 tests | 0 | app/mcp_client.py, fake stdio server fixture |
| MCP routes + Settings UI + tests | 12 | nested | haiku | 131,408 | 17 | 3m02s | pass, +27 py +12 fe | 0 | app/mcp_routes.py, static/mcp_settings.js |
| lead 12 (own context) | 12 | nested | sonnet | 164,457 | 33 | 20m46s | +5 integration tests (pass with patches) | 0 | wrote patches, docs/mcp.md, integration test |
| reviewer 05 | 05 | nested | sonnet | 113,039 | 10 | 1m42s | APPROVE, 0 blocking | 0 | 5 nits |
| reviewer P02 | P02 | nested | sonnet | 105,585 | 12 | 1m26s | CHANGES REQUESTED, 1 blocking (timer leak on failed tile) | 0 | 4 nits; orientation question to user |
| reviewer 12 | 12 | nested | sonnet | 118,610 | 18 | 1m45s | CHANGES REQUESTED, 2 blocking (DNS-rebinding RCE on /api/mcp, corrupt json breaks chat) | 0 | 5 nits; consent question to user |
| P02 fix-up 1 | P02 | nested | sonnet | 156,795 | 6 | 1m03s | fe 268/269 known; py 571 pass | 1 | lead fixed registry destroy of failed tiles directly |
| 12 fix-up 1 | 12 | nested | sonnet | 185,538 | 12 | 1m52s | py mcp tests 130 + integration 5 (needs 12-fix-main patch); fe 268/1 known | 1 | DNS-rebinding guard, corrupt-config tolerance, approval shows args, process-group kill; patch 12-fix-main.py.diff pending |
| P04 shell, boot receiver, tests (lead did it directly, no coder) | P04 | nested | sonnet | 100,533 | 14 | 2m44s | pass, +3 tests | 0 | no Haiku spawned: change was one Java file + small tests |
| eink.py render module | P05 | nested | haiku | 96,396 | 5 | 1m10s | pass | 0 | 7 widget renderers + render_page |
| test_panels_eink.py | P05 | nested | haiku | 81,791 | 8 | 1m15s | pass, +17 tests | 0 | |
| lead P05 | P05 | nested | sonnet | 116,888 | 22 | 4m16s | py 665 pass; +4 wiring tests | 0 | route written by lead |
| 06 files search | 06 | nested | haiku | 90,437 | 10 | 1m02s | pass, +19 tests | 0 | mdfind argv, roots whitelist |
| 06 sources+consent | 06 | nested | haiku | 93,553 | 8 | 0m46s | pass, +23 tests | 0 | FilesConsent third consent |
| 06 orchestrator module | 06 | nested | haiku | 95,225 | 11 | 0m57s | pass, +15 tests | 0 | SmartSearch, docs |
| 06 lead | 06 | nested | sonnet | 123,802 | 23 | 6m23s | py 738/1 other-agent fail; fe 423/1 known | 0 | patches 06-* pending |
| backend everyday service | P07 | nested | haiku | 112,157 | 13 | 4m55s | pass, +35 py | 0 | |
| clock upgrade | P07 | nested | haiku | 112,659 | 13 | 2m00s | pass, +9 fe | 0 | |
| info widgets | P07 | nested | haiku | 120,266 | 11 | 2m19s | pass, +22 fe | 0 | |
| productivity widgets | P07 | nested | haiku | 123,767 | 9 | 2m38s | pass, +17 fe | 0 | |
| timers widgets | P07 | nested | haiku | 124,271 | 9 | 2m38s | pass, +14 fe | 0 | |
| P07 lead | P07 | nested | sonnet | 143,129 | 28 | 8m27s | py 739, fe 440/1 known | 0 | |
| reviewer P04 | P04 | nested | sonnet | 90,200 | 5 | 2m42s | CHANGES REQUESTED, 1 blocking (onPageFinished cancels reconnect) | 0 | fix-up not sent: user stopped the push |
| lead P03 (stopped) | P03 | nested | sonnet | ? | ? | ? | unfinished, uncommitted | — | stopped by the orchestrator when the user ended the push |
| P04 reconnect fix + review | P04 | handoff | antigravity | — | — | — | py 739 pass; fe 440/441 (known minipet) | 0 | mainFrameError guard in MainActivity + APK build green; fresh research reviewer APPROVE; commit fe1f749 |
| P05 review + checklist/corrupt fix + re-review | P05 | handoff | antigravity | — | — | — | py 742 pass; fe 440/441 (known minipet) | 1 | added checklist support, corrupt pages/today guards, non-pinning refresh URL; fresh re-reviewer APPROVE; live /eink OK; commit 27223b9 |
| 06 wiring + review + fixes + re-review | 06 | handoff | antigravity | — | — | — | py 746 pass; fe 441/442 (known minipet) | 1 | applied 06-* patches; fixed Ollama files consent label, eager provider-switch reset, NFD/binary hardening, +wiring/frontend tests; fresh re-reviewer APPROVE; live /api/data-consent OK; commit 4d107b5 |
| P07 wiring + review + fixes + re-review | P07 | handoff | antigravity | — | — | — | py 747 pass; fe 443/444 (known minipet) | 1 | wired register_everyday + calendar_reader; fixed .pn-remove/.pn-status CSS collisions, .pn-input select, checklist include_done refresh, timers stale GET guard, runtime input key guard; fresh re-reviewer APPROVE; live /panel, /api/panel/* OK; commit 10cf07a |
| P03 completion + review + fixes + re-review | P03 | handoff | antigravity | — | — | — | py 750 pass; fe 446/447 (known minipet) | 1 | wired /editor & /api/credentials, built static/editor/{editor.js,editor.css,index.html}, fixed ephemeral editor preview in DeviceHub & editor-preview.js; fresh re-reviewer APPROVE; live /editor, /api/credentials, /api/layout-templates OK; commit 99a48f6 |
