# Agent workflow report: nested vs team vs baseline

Build push of 2026-11-18 on branch `lupin-foco`. Source data: `.scratch/agents/ledger.md`.

## Short answer

- **Agent teams** could not be measured. The desktop app does not expose them, even with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`: a spawn with a team name ran as a plain subagent and no team was created.
- **Baseline (one Sonnet agent per issue) beat nested (Opus → Sonnet lead → Haiku coders)** in the one head-to-head test, issue 07 Dictation:
  - The baseline cost about **4× fewer tokens**, finished **faster** and wrote **less code**.
  - It passed review after one small fix.
  - The nested build was reverted.
- What made the push work was the **fresh Sonnet reviewer** on every issue, not the Haiku layer. Leads reported "0 fix-ups" on nearly every coder task. Reviewers still found blocking problems in 6 of the 9 issues they checked, including one remote-code-execution hole.
- **Recommended setup:** an Opus orchestrator, **one Sonnet builder per issue** (no Haiku coders), then a fresh Sonnet reviewer, with the orchestrator applying patches to shared files.

## How to read the numbers

- **Tokens** are the `subagent_tokens` figure from each agent's usage block. It behaves like the agent's **final context size**, not the total tokens it consumed. For example, a fix-up on a resumed agent raised it from 133,336 to 135,007. Real consumption is higher, since every turn re-reads the context. Treat these numbers as a lower bound that is fair for comparing agents with each other.
- **Fixed overhead:** every subagent starts at about **69k tokens** before it does anything. A one-word smoke test cost 68,991.
- **Not counted:**
  - My own (orchestrator) usage.
  - Fix-up rounds on resumed agents, because their figures are cumulative.
- **Wall times** are per agent. Coders inside one issue often ran in parallel, so adding up their times overstates elapsed time.

## Head-to-head: issue 07 (Dictation)

| | Baseline (1 Sonnet) | Nested (Sonnet lead + 4 Haiku) |
|---|---|---|
| Tokens | 133,336 | 572,063 (lead 132,215 + coders 439,848) |
| Wall time | 3m33s | 5m11s (lead) |
| Code | ~270 lines + ~150 test lines | ~750 lines + ~1,100 test lines |
| Review | approved after 1 small fix (clipboard restore in `finally`) | 3 blocking issues |
| Outcome | merged (3223ef2) | reverted (18ee755) |

The nested build's three blocking issues:
- wiring that was never applied;
- spoken strings hardcoded outside the speech tables;
- a blocking await that could not be cancelled.

Each coder built a correct piece in isolation, but nobody owned how the pieces fit together. The lead's review didn't catch that.

## Every issue in the push

Build tokens = lead + its coders. The review column is the fresh reviewer's first verdict.

| Issue | Coders | Build tokens | Lead time | Review (blocking) | State |
|---|---|---|---|---|---|
| P01 Device Roles | 4 | 547,697 | 9m42s | approved (a product gap was found before review: every device would have become Panel-only) | done |
| P06 Signals | 1 | 228,639 | 4m17s | approved, 3 follow-ups fixed | done |
| 11 Local mode | 3 | 439,936 | 5m02s | 2 (timer leak, undefined name) | done |
| 07 Dictation (nested) | 4 | 572,063 | 5m11s | 3 | reverted, baseline kept |
| 05 Tasks, notes, habits | 4 | 606,382 | 10m10s | 0 | done |
| P02 Panel runtime | 5 | 896,314 | 13m47s | 1 (widget timer leak) | done |
| 12 Lupin MCP | 3 | 558,111 | 20m46s | 2 (DNS-rebinding RCE on `/api/mcp/*`, corrupt config broke chat) | done |
| P04 Android shell | 0 (lead alone) | 100,533 | 2m44s | 1 (reconnect cancelled by `onPageFinished`) | built, fix not sent |
| P05 E-ink Mode | 2 | 295,075 | 4m16s | not reviewed | built and wired, unreviewed |
| 06 Smart search | 3 | 403,017 | 6m23s | not reviewed | built, patches not applied |
| P07 Everyday widgets | 5 | 736,249 | 8m27s | not reviewed | built, patch not applied |
| P03 Mac Layout editor | — | — | — | — | stopped mid-build, uncommitted |

Totals, lower bound:
- **Build:** about 5.38M tokens. Haiku coders account for 3.93M of that, over 34 coder tasks.
- **Review:** 8 reviewers, about 0.81M tokens.
- **Baseline and probes:** about 0.27M tokens.
- **Overall:** about **6.5M tokens**, not counting my own usage.

## Findings

1. **The Haiku layer is mostly overhead.** With 34 coders at about 69k fixed overhead each, roughly **2.35M tokens (60% of coder tokens)** went to start-up context before any work. The lead also has to write a fully specified brief for each coder, which it could have spent writing the code itself. P04's lead skipped coders for a one-file change, and that issue was the cheapest by far.
2. **"0 fix-ups" measured the wrong thing.** Leads reviewed each coder's diff against the coder's own brief, so almost every task passed first time. Problems showed up where pieces met:
   - wiring and lifecycle;
   - security boundaries;
   - Android callback order.

   Only the fresh reviewer, who read the whole issue against the spec, caught these.
3. **Fresh reviewers paid for themselves.** Each one cost about 90–120k tokens and took 1–3 minutes. Between them they caught:
   - an RCE path;
   - two resource leaks;
   - a reconnect bug that would have stranded the kiosk;
   - a chat-breaking crash on a corrupt file;
   - the nested 07's integration gaps.
4. **Nested code was bigger.** Splitting work across coders produced more code and many more tests per feature (07: about 3× the code and 7× the tests). Each piece was well tested, but the tests didn't cover how the pieces fit together, which is where the bugs were.
5. **Patch files for shared files worked, with friction.**
   - Leads couldn't edit `app/main.py`, and their try-and-revert attempts were sometimes blocked by the permission classifier, so I applied every patch myself.
   - One patch had hand-written hunk headers and didn't apply (P05), so I applied it by hand.
   - Until the issue 12 patches were applied, its integration test hung the whole Python suite.
   - Patch files committed by leads add clutter to `.scratch/agents/patches/`.
6. **Parallel leads mostly respected file ownership.** No two leads edited the same file. They did hit each other's in-progress tests: P07's untracked `test_panels_everyday.py` failed in other leads' runs, and so did P05's `test_panels_eink.py` before it was committed.
7. **Product questions surfaced at the right level.** Leads stopped and asked instead of deciding, for example on P01's default roles and 07's gesture. A few still decided on their own, such as P02's portrait 6×12 grid, and the reviewer flagged that.

## Recommended setup

- **Orchestrator (Opus):** plans waves, owns shared files, applies patches, runs both suites, restarts the server and checks it live.
- **Builder (one Sonnet per issue):** writes the code and tests itself, with no Haiku coders. It splits work only when an issue has truly independent parts that are each larger than about 69k tokens of work. It sends patches for shared files.
- **Reviewer (fresh Sonnet per issue):** checks acceptance criteria, security and integration, and blocks only on real bugs. Its fix-up goes back to the builder, which still has its context.
- **Gate:** an issue is done only after review approval, both suites green and a live check, as the specs already require.

Expected effect, judging from 07 and P04: about **3–5× fewer build tokens** and less code to review, with the same review quality, since the reviewer is what catches the real bugs.

Caveat: there is only one controlled comparison (07). The other issues had no baseline twin, so the cost estimate rests on 07 and on the overhead arithmetic.

## Where the push stopped

The user stopped the push during wave 4.

- **Done (reviewed, wired, checked live):** P01, P06, 11, 07 (baseline), 05, P02, 12.
- **Built, not finished:**
  - **P04:** committed (e160919). The reviewer's reconnect fix was not sent.
  - **P05:** committed and wired (c2690de, 3c839d1), but not reviewed.
  - **06:** committed (f3db8df). The `06-main.py`, `06-app.js` and `06-index.html` patches are not applied, and it is not reviewed.
  - **P07:** committed (ffbd3db). `P07-main.py.diff` is not applied, and it is not reviewed. Open question: should `/api/panel/calendar` be Mac-only?
  - **P03:** stopped mid-build. Its uncommitted work is left in the tree for a decision on keeping it:
    - edits to `app/panels/templates.py` and `tests/test_panels.py`;
    - new `app/panels/credentials.py`, `static/editor/`, `custom/`, and editor and template tests.
- **Not started:** P08, P09, P10, Lupin 04, Lupin 08.
- **Open user questions:**
  - Should portrait Panels use 6×12 or 12×6?
  - Should `lupin_read_today` need Data Consent for Cowork tasks?
  - Should the Android shell open the page that matches the device's role?
- **Known follow-ups:**
  - The mini-pet frontend test failure.
  - `SecretRedactingFilter` breaks uvicorn access logs.
  - Patch-file clutter in `.scratch/agents/patches/`.
  - `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` can be removed from `~/.claude/settings.json`.
