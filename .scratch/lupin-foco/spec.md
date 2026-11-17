# Lupin in focus

Direction (ADR 0001): Lupin is the product. Mac control, Cowork, Shortcuts and assistant features are ways for Lupin to help, not products of their own. The Brain runs on the Mac; the Body (ESP32-S3 JC4832W535, 3.5" 480x320, Arduino + LVGL) shows Lupin, plays the sound and senses the user. Every feature is born on the RG406H and then ported to the ESP32. When the ESP32 arrives, it becomes the Active Body and the RG406H becomes Dock (and a Body when the ESP32 is off).

## Execution rule

- Features come **one at a time**, in the order 02..08.
- Each feature must **survive 1 week of real use** (at least 4 days of use, with no irritating bug) before the next one starts.
- Offline operation is **not** a requirement.
- Don't add Bodies or Modes without revisiting ADR 0001.

## Issues

| # | Issue | Status |
|---|-------|--------|
| 01 | Cuts | done |
| 02 | Living Body: Brain-Body protocol | done, in daily use |
| 03 | Morning: First Wake | done, in daily use |
| 04 | Presence | needs-triage |
| 05 | Tasks, notes and habits by voice | needs-triage |
| 06 | Smart search | needs-triage |
| 07 | Dictation | needs-triage |
| 08 | Image editor | needs-triage |
| 09 | Dock redesign | done (RG406H test pending) |
| 10 | Lupin's look: layered husky | first art delivered |
| 11 | Fully local mode | needs-triage |
| 12 | Lupin as an MCP server | needs-triage |
| 13 | Showcase: README, video and opening the repo | needs-triage |
| 14 | Translate the project to English | done |
| 15 | Lupin's language setting | done (RG406H test pending) |

Issue 01 comes before everything (clears the ground). Issue 09 is not in the 02..08 queue and only starts once the ESP32 is in use, or when the user decides.

The cut code lives only on the `snapshot/swarm-2026-11-16` branch.
