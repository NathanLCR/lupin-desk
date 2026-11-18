# 04 - Presence

Status: ready-for-agent

## Context

Presence is Lupin being on the desk while the user works, reacting to what happens. Depends on 02 and runs on the Active Body.

## Scope

- Break reminders based on continuous working time.
- Reactions to the time of day, to voice and to touch.
- Music playing as seasoning (Now Playing), not as the focus.
- The Mac's active app only in the background, as context, without Lupin commenting on it or logging it intrusively.
- Reactions come from the Brain (Expression and Mood), never from the Body's own logic beyond idle behaviours.

## Acceptance criteria

- [ ] Lupin suggests a break after a configurable stretch of continuous work.
- [ ] Reactions change with time of day, voice and touch.
- [ ] Music influences the tone without dominating the behaviour.
- [ ] The Mac's active app is only used in the background.
- [ ] No reminder is repetitive or annoying (frequency limit).
- [ ] 1 week of real use (min. 4 days) without an irritating bug.

## Open questions

- What is the default break interval, and how does the user adjust it?
- What counts as "continuous work" (keyboard activity, active app)?

## Decisions (grill 2026-11-18)

- Continuous work = the Mac's keyboard/mouse input within the last 5 minutes, read from HIDIdleTime (`ioreg`, added to the whitelist). A break = 5+ minutes idle. No app logging.
- Break reminder after 50 minutes of continuous work by default; adjustable in Settings and by voice ("remind me every hour"). A touch snoozes 10 minutes. At most one reminder per 20 minutes. Muted during a Pomodoro.
- Time of day drives Energy: sleepy late at night, brighter in the morning.
- Touch/petting raises Affinity with a happy Expression; voice reactions through the normal turn.
- Now Playing's tempo/genre nudges tone (calmer/livelier), never triggers speech.
- Break reminders go through Signals (panels P06).
- The "1 week of real use" criterion is replaced by the spec-then-code gate (ADR 0002); daily use is checked after.
