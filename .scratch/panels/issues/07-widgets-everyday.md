# P07 - Widgets: Everyday

Status: ready-for-agent
Blocked by: P02, P06

## Scope

- Clock (analog/digital, several time zones), weather (Open-Meteo, no key), now playing with play/pause/next (Mac media, via whitelisted commands), calendar (read-only Mac calendar), notes, checklists and habits (the store from lupin-foco issue 05), Pomodoro (the existing one), timers, internet radio if cheap.
- Each widget declares sizes, topics, actions and, where sensible, an e-ink render.
- Timer done, habit due and meeting soon emit Signals.

## Acceptance criteria

- [ ] Each widget works on the RG406H and an iPad.
- [ ] Notes/checklists ticked on a Panel are the same items Lupin reads by voice.
- [ ] No calendar data reaches an LLM without Data Consent.
