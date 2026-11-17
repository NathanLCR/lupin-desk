# Companion-first: the Mac is the Brain, a small ESP32 screen is the Body

By November 2026 the Desk Assistant had grown wide (pet, copilot, Dock, Stream Deck, Ambient Display, Cowork, Diagnostics, Electron, Android, iPhone): the features were built all at once, none of them was great, and none was in daily use. We decided that Lupin is the product. Mac control, Cowork, Shortcuts and assistant features (inspired by Taby: inbox, calendar, focus and habits, smart search, dictation…) are ways Lupin helps, not products of their own. They are all in scope, but **one at a time**: each has to be great and in daily use before the next starts.

The architecture follows the "physical Taby" model. The **Brain** is the server on the Mac: LLM, memory, Mood, Today, Cowork and Mac control. A **Body** only shows Lupin, plays sound, and senses touch, voice and buttons. The Brain decides the Expression; the Body animates it and handles small idle behaviours (blinking, glancing around) on its own. Lupin's main Body is an **ESP32-S3 board with a 3.5" touchscreen (JC4832W535)** standing on the desk. Each feature is built first on the RG406H (which is already working) and then ported to the ESP32 once the board arrives. After that, the RG406H becomes the Dock (Mac control) and can still act as a Body. The Mac mini-pet is a secondary Body. The iPhone only has to open: it gets no design work of its own, and its bugs don't block anything.

## Considered Options

- **Brain streams pixels to the Body** (JPEG over WebSocket): rejected. Wi-Fi latency would show in the animation, and Lupin would only look alive while the Mac is responsive.
- **Assistant-first** (Lupin as a skin over a Taby-like feature set): rejected. The face and the presence on the desk are what make this product different.
- **All features at once**: rejected. That's how we got here.

## Consequences

- The main Body runs native firmware (Arduino + LVGL via PlatformIO) and draws Lupin's face itself. The web face (`static/lupin.js`, `audio_synth.js`) doesn't run there, so Lupin's look gets redone for 480×320.
- Brain and Body talk over a single WebSocket opened by the Body: JSON events (Expression, Mood, the sentence being spoken, touch) and audio chunks for the voice. This protocol is a contract that both sides follow.
- Lupin lives in only one Body at a time (the Active Body): the ESP32 whenever it is connected, otherwise the RG406H. While the ESP32 is active, the RG406H is just the Dock.
- The RG406H web Body talks to the Brain **only** through the same protocol the ESP32 will use, so porting to the ESP32 is just writing firmware.
- Lupin's voice comes out of the Body. Listening happens on the Mac's microphone, started by touching the Body (tap-to-talk), as long as the board has no microphone.
- Offline operation is not a requirement for now.
- Future agents and swarms must not build more than one feature at a time, nor add Bodies or Modes, without revisiting this ADR.

## Addendum (2026-11-17): talking to Lupin from any device

"Lupin lives in only one Body" first meant that a device that isn't the Active Body gets nothing from Lupin. That turned out too strict: the user wants to talk to Lupin from whatever is in their hand (the RG406H while it is only the Dock, the Mac, the iPhone). So any device can talk to Lupin, but the reply always plays in the Active Body (voice, face, Expression), and the device the user spoke from gets only the text, with no audio. Without an Active Body connected, that device gets the text alone.

Rejected: answering on the device that asked (Lupin would appear in two Bodies) and refusing to talk from a device that isn't the Active Body (the user would have to walk to the ESP32 to ask anything).

Consequence: the Brain routes a turn's voice and Expression to the Active Body, which may be a different connection from the one that sent the text or audio.

## Addendum (2026-11-17): positioning, and the portfolio adds no features

A market survey (`docs/market-research.md`) found two crowded camps. Companion robots (EMO, Loona, Eilik, Vector) have a body and a personality but do no real work. Assistants (Taby, the Autonomous Lamp, Mac assistants) do real work but have a thin character or none. Lupin sits where they meet: **a desk companion that actually works**. He has a body and a Mood, he acts on the user's Mac and Cowork, and the user's calendar and email reach an LLM provider only through explicit Data Consent. This sentence is the test for any new feature: a feature that only makes Lupin cuter, or only makes him more useful without going through Lupin, needs a reason.

The project is also a portfolio piece. The portfolio gets **presentation only** (README, video, write-ups), never features of its own. Features still come one at a time, from daily use. Rejected: picking features because they demo well (camera, physical movement), which is how the project got wide in the first place.
