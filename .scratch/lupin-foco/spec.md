# Lupin in focus

Direction (ADR 0001): Lupin is the product. Mac control, Cowork, Shortcuts and assistant features are ways for Lupin to help, not products of their own. The Brain runs on the Mac; the Body (ESP32-S3 Guition JC3248W535, 3.5" 480x320, Arduino + LVGL) shows Lupin, plays the sound and senses the user. Every feature is born on the RG406H and then ported to the ESP32. When the ESP32 arrives, it becomes the Active Body and the RG406H becomes Dock (and a Body when the ESP32 is off).

## Execution rule (updated by ADR 0002, 2026-11-18)

- Lupin is one of two pillars; Panels (`.scratch/panels/`) is the other.
- **Spec-then-code gate** replaces the one-week gate: each issue is grilled in a planning session (Opus), coded by subagents, reviewed and tested, then marked done. Daily use is checked afterwards and feeds new issues.
- Issues 04, 05, 06, 07, 08, 11 and 12 are specced (see each file's *Decisions* section) and may be built in parallel when their files don't overlap.
- This track is built with an **agent team** (experimental). Issue 07 is also built Sonnet-only as the workflow baseline.
- Offline operation is still not a requirement (11 makes it possible).

## Issues

| # | Issue | Status |
|---|-------|--------|
| 01 | Cuts | done |
| 02 | Living Body: Brain-Body protocol | done, in daily use |
| 03 | Morning: First Wake | done, in daily use |
| 04 | Presence | ready-for-agent |
| 05 | Tasks, notes and habits by voice | done (live voice check and 1-week use pending) |
| 06 | Smart search | done (live voice check and 1-week use pending) |
| 07 | Dictation | done (real-app paste and daily use pending) |
| 08 | Image editor | ready-for-agent |
| 09 | Dock redesign | done (RG406H test pending) |
| 10 | Lupin's look: layered husky | first art delivered |
| 11 | Fully local mode | done (Kokoro install and live voice check pending) |
| 12 | Lupin as an MCP server | done (real Claude Code registration and an external server pending) |
| 13 | Showcase: v0.1 public release | ready-for-agent |
| 14 | Translate the project to English | done |
| 15 | Lupin's language setting | done (RG406H test pending) |

Issue 01 comes before everything (clears the ground). Issue 09's Dock becomes a widget group on Panels (panels P10).

The cut code lives only on the `snapshot/swarm-2026-11-16` branch.
