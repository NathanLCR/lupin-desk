# Two pillars: Lupin and Panels on repurposed devices

Status: accepted (2026-11-18). Supersedes parts of ADR 0001, listed at the end.

ADR 0001 said Lupin is the product and cut the dashboard-like surfaces (Dock as a product, Stream Deck, Ambient Display) because everything had been built at once and nothing was good. Looking back, the cause was not the number of features. It was **deciding and coding in the same agent session**: one agent made the product decisions and wrote the code together, so the result was badly made and bloated.

[PhoneBox](https://github.com/ersinkoc/phonebox) (MIT) turns an old Android phone into a desk panel: system stats, AI coding sessions with Claude Code permission prompts, music, touch controls, a browser layout editor and about 120 widgets. It captures one of the starting ideas of this project. So the Desk Assistant now has **two equal pillars**:

1. **Lupin**, the desk companion that actually works (ADR 0001, unchanged in spirit).
2. **Panels**: old devices the user already owns (phones, tablets, an iPad, a laptop, a Kindle, the RG406H) become desk panels showing pages of widgets, next to the ESP32 Body.

We take **ideas only** from PhoneBox, never its code.

## Decisions

- **Device Roles.** Each device the user connects gets a role chosen per device: Body, Panel, or Body + Panel. A Body + Panel device shows Lupin as one of its pages.
- **Active Body by priority.** Lupin still lives in one Body at a time. The user orders the Body devices on the Mac (for example ESP32 > RG406H > tablet), and the highest-ranked connected one is the Active Body.
- **One protocol.** Panels use the same single WebSocket as the Body protocol, extended so a device announces its roles, subscribes to the data topics of the widgets on its pages, and sends actions **by ID only**. The Kindle polls HTTP instead.
- **Layouts.** A Layout is a named set of pages of widgets on a grid (12 × 6 like PhoneBox, with portrait and landscape variants and templates). Each device is assigned one Layout, and several devices may share one. Layouts are edited in a browser editor on the Mac. A device can only arrange its pages (move, resize, add or remove a widget); widget settings, data sources and templates stay on the Mac.
- **Runtimes.** The Brain serves Panels as a web app. Old Android devices use the existing WebView shell, with minSdk lowered from 26 to 24 (Moto G5, Android 7) and a first-run screen to pick the Brain's address and the device's role. iPad and iPhone use Safari. The Kindle gets an **e-ink page mode**: black and white, rendered on the server, no animation, refreshed every few minutes.
- **Signals.** Widget data sources emit Signals (Claude Code needs you, CI failed, timer done, habit due, meeting soon). Lupin reacts with an Expression, and he speaks up unprompted only for a short list of important Signals. During a Pomodoro he stays quiet except when Claude Code needs the user.
- **Credentials stay on the Mac.** Keyless and local sources come first (Open-Meteo, the Mac calendar, the `gh` CLI login). Tokens for Home Assistant, OBS and similar services are entered in the Mac editor and stored in `.env` on the Mac. They are never sent to devices or written to logs.
- **Data Consent gains files.** File contents found by smart search reach an LLM provider only with a third Data Consent (files), next to calendar and email.
- **Language.** The Brain stays Python (FastAPI). It is I/O-bound, depends on mlx-whisper, and has about 250 tests; a rewrite would buy nothing. A small Go sidecar may collect Mac stats if polling them in Python turns out heavy. The ESP32 firmware stays C++/LVGL.

## Security: the LAN is trusted

The user chose to **trust the local network**: Panels connect without the access token (`DESK_ACCESS_TOKEN`) that the Brain requires today. The user was told the risk: anyone on the same Wi-Fi (a guest, a compromised IoT device) can view every Panel and send any action a Panel can send, including **Allow** on a Claude Code permission prompt.

What still holds:

- Devices send action IDs, never commands. `app/mac_control.py` keeps its strict whitelist (`subprocess.run` with an argv list, never `shell=True`).
- Calendar, email and file contents still follow Data Consent.
- Credentials never leave the Mac.
- The Claude Code hooks are opt-in, installed by an explicit setup button on the Mac.

Revisit this choice before the Brain is reachable from outside the home network (Tailscale, port forwarding) or before the project is published for other people to install.

## Process: decide here, code elsewhere

The "survives one week of real use" gate from ADR 0001 is replaced by a **spec-then-code gate**. Every feature is grilled and specced in a planning session (Opus) before any code is written, then coded by subagents (Sonnet leads, Haiku coders), then reviewed and tested before it is marked done. Daily use is checked afterwards and feeds new issues; it no longer blocks the next feature.

Several features may now be built at the same time, split by files so that no two agents touch the same file.

## Considered options

- **Lupin first, Panels around him**: rejected. The user wants the panel platform to be a product of its own.
- **Panel platform first, Lupin as a widget**: rejected. Lupin's presence is still what makes the project different.
- **Lupin on every screen at once**: rejected. Lupin appearing in two Bodies stays confusing (ADR 0001, addendum of 2026-11-17).
- **Rewrite the Brain in Go or Rust**: rejected. See *Language* above.
- **QR pairing with per-device permissions**: considered and recommended, but the user chose to trust the LAN.

## What this supersedes in ADR 0001

- "Lupin is the product." Lupin is now one of two pillars.
- "One feature at a time, each in daily use before the next." Replaced by the spec-then-code gate.
- "The iPhone only has to open." The iPad and iPhone are supported targets **as Panels**; as Bodies they stay best-effort.
- "Future agents must not add Bodies or Modes without revisiting this ADR." Device Roles and Layouts are now the way to add surfaces. New *kinds* of device still need an ADR.

Everything else in ADR 0001 stands: the Brain/Body split, the Body draws Lupin itself, one Active Body, tap-to-talk on the Mac's microphone, and offline operation not being a requirement (issue 11 makes it possible, not required).

## Addendum (2026-11-18): Allow only from the device showing the prompt

Grilling P09 narrowed the LAN-trust risk for Claude Code permission prompts without adding pairing. The Brain accepts Allow or Deny only from a device that is showing that prompt right now, using a one-time ID per prompt. An unknown, used or expired ID, or an answer from a device that isn't showing the prompt, is rejected. A prompt waits 2 minutes, then Claude Code shows its own prompt. Everything else in *Security: the LAN is trusted* stands: anyone on the Wi-Fi can still see Panels and send other Actions.

The idea comes from the trust rules of Meta's Muse Gadgets video port (`.scratch/research/muse-gadgets.md`): an unauthenticated endpoint takes input only while the user is looking at it.
