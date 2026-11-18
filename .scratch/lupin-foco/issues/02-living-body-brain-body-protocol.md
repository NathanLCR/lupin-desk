# 02 - Living Body: Brain-Body protocol

Status: done, in daily use (1-week check pending)

## Context

Feature 1 in the queue. The main Body will be an ESP32-S3 Guition JC3248W535 (3.5" 480x320, touch, Arduino + LVGL) once it arrives; then it becomes the Active Body and the RG406H becomes Dock (and a Body when the ESP32 is off). So that porting is only a matter of writing firmware, the RG406H web Body must talk to the Brain exclusively through the protocol the ESP32 will use (ADR 0001).

## Scope

- Define the Brain-Body WebSocket protocol, opened by the Body: JSON events for Expression, Mood, the sentence being spoken and touch, plus audio chunks of the voice.
- Document the protocol as a contract (version, event types, fields).
- Implement the Brain side of the protocol.
- Migrate the RG406H web Body to use only this protocol, with no parallel endpoints.
- Guarantee a single Active Body at a time.
- No ESP32 firmware in this issue.

## Acceptance criteria

- [x] A protocol document exists with all events and JSON examples.
- [x] The Brain sends Expression, Mood, spoken sentence and audio; it receives touch over the same WebSocket.
- [x] The RG406H web Body uses no other channel to show or hear Lupin.
- [x] Lupin is never in two Bodies at the same time.
- [x] The Body handles small idle behaviours on its own (blinking, looking around).
- [ ] Real use on the RG406H for 1 week (min. 4 days) without an irritating bug before starting 03.

## RG406H test feedback (2026-11-16) and decisions

- The top bar (Pet/Dock + 9 actions) is confusing: it goes away. Pet has no bar; a discreet button + `Start` open Settings; Pet↔Dock by `L1`/`R1` or swipe; Expressions moves to Settings › Diagnostics; Memory, sounds, voice and captions go to Settings; automatic fullscreen; "pin bar" removed.
- Settings: Voice and sound, Brain (provider/model, Mac address over Wi-Fi/USB), Memory, Skills, Dock (only view Shortcuts), Diagnostics.
- Lupin's look is wrong: he is the black-and-white cartoon husky from the reference (cyan eyes, two cyan dots, cyan outline, white muzzle, pink nose, collar with a cyan wave). Bust as the default; full body only in Tricks. Layered animation (head, eyes, eyelids, eyebrows, mouth/tongue, ears, collar), identical on web and LVGL.

### Delivery order (2026-11-16)

1. First the bar removal + Settings (discreet button, `Start`, `L1`/`R1`/swipe, Diagnostics with Expressions), in its own commit.
2. Then the layered husky (issue 10), in another commit.
3. The old EMO face (`face.js`/`face.css`) is removed when the husky lands; it does not stay as a fallback. The Expressions panel in Diagnostics shows the husky from then on.

### Delivered: step 1 (bar and Settings)

- [x] Pet without the top bar; only a discreet button (gear with a connection dot) in the corner.
- [x] Settings with 6 sections: Voice and sound, Brain (connection, Mac address, provider and model, read-only), Memory, Skills, Dock (only lists the Shortcuts) and Diagnostics (Expressions and States).
- [x] `Start` opens/closes Settings; `B`/`Esc` close them; `L1`/`R1` switch Mode (Pet↔Dock) and, inside Settings, switch section. A quick horizontal swipe and `Alt`+arrows do the same.
- [x] Automatic fullscreen on the first touch or key (`Select` still toggles); "pin bar" removed.
- Out of this step: changing address/provider/model from the RG406H (stays on the Mac); the EMO face stays until step 2 (issue 10).
- The mini-pet test `minipet-state.test.cjs` was already failing before (label "Ativar som"); it is not part of this step.

### Active Body (2026-11-17)

- The Brain picks one Active Body: `esp32` > `rg406h-web` > `web`; within the same type, the latest `hello` wins. The others receive `active_body` with `active: false` and become Dock only (no Pet, no voice). User decision: the device without Lupin stays as Dock, it is not disconnected.
- The page identifies itself as `rg406h-web` only on Android; the Mac browser and the iPhone are `web`, so they don't steal Lupin from the RG406H.
- Blinking and looking around already belong to the Body (`lupin.js`); the blink uses the closed-eyes bust.
