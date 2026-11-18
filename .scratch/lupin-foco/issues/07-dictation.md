# 07 - Dictation

Status: done (baseline build merged; real-app paste and 1-week use pending)

## Context

Inspired by Taby (dictation): the user speaks and the text appears in the focused app on the Mac. Listening uses the Mac's microphone, started by a touch on the Body (tap-to-talk). Comes after 06.

## Scope

- Start and stop dictation by touching the Body.
- Insert the text into the Mac's active app.
- Define corrections and punctuation.

## Acceptance criteria

- [ ] Touch start/stop flow defined.
- [ ] The text reaches the focused app reliably.
- [ ] Lupin gives feedback (Expression) while listening.
- [ ] Speech recognition provider decided, and where the audio goes.
- [ ] 1 week of real use (min. 4 days) without an irritating bug.

## Open questions

- Local or cloud recognition?
- How to insert the text (Accessibility, paste, keystrokes)?

## Decisions (grill 2026-11-18)

- Recognition: local mlx-whisper (already in the Brain); audio never leaves the Mac.
- Insertion: clipboard paste into the focused app, then the previous clipboard is restored.
- Touch the Body to start and stop; Lupin shows a listening Expression.
- This is the **baseline feature** for the workflow report: it is built twice, by the agent team and by a Sonnet-only run in its own worktree, and only one version is merged.
