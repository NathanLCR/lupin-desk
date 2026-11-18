# Market research: AI desk companions (November 2026)

Goal: understand what exists that resembles Lupin, what each product is good at, where it falls short, and what that says about Desk Assistant as a personal product and as a portfolio piece.

## The market map

The market splits into five groups.

### 1. Companion robots (closed hardware, built around cuteness)

| Product | Price | Good at | Falls short |
|---|---|---|---|
| **EMO** (Living.AI) | US$ 279 (US$ 379 with dock) | Over a thousand expressions, walks around the desk without falling, recognizes up to 10 faces, chats through ChatGPT | ~2 h battery, English-only voice, unstable app, weak support, 2.4 GHz Wi-Fi only. Scripted reactions; does no tasks |
| **Loona** (KEYi) | US$ 429 | The most "dog-like": roams the house, returns to its dock by itself, ChatGPT-4o with no subscription | ~2 h battery, noisy motor, sometimes can't find its charger |
| **Eilik** (Energize Lab) | US$ 140 | Cheap, offline, no app or account, 8-10 h battery, has a Pomodoro timer | Doesn't talk; it is an expressive toy |
| **Vector 2.0** | US$ 250 + yearly plan | Autonomous personality, fans of the original | Voice sits behind a subscription. Anki, the original company, went under and the robot nearly became a paperweight |
| **Moflin** (Casio) | n/a | Strong emotional bond, audio stays on the device (privacy) | Doesn't speak, does nothing; motor hums |
| **LOOI** | US$ 180-220 | Cheap, uses your phone as brain and face, ~5 h | Ties up your phone; slow on an older phone |

**Pattern:** they all sell **presence and personality**. Almost none is useful. The complaints repeat: battery, a bad app, mandatory cloud, subscriptions, and the risk of the company disappearing and the robot dying with it.

### 2. Desk robots that "work" (the group closest to Lupin)

- **Autonomous Lamp** (US$ 699): an open-source desk robot that runs agents (Claude Code, Codex, OpenCode...) and installable skills, such as water, break and posture reminders, plus calendar and Home Assistant. It lets you swap the agent and use your own keys. Plugged in, no battery, and no track record with owners yet.
- **Reachy Mini** (Hugging Face/Pollen, US$ 399-499): a kit for people who code. It does whatever you program.

Autonomous's own blog proposes a three-question test to tell a companion from a "robot that works":
1. Can you choose the AI?
2. Does it act outside its own body (calendar, computer)?
3. Can you change its skills without waiting for the manufacturer?

**Lupin passes all three:** he has a selectable provider (including local Ollama), acts on the Mac (Shortcuts, Dock, Cowork Tasks) and has Skills. Almost all of group 1 fails all three.

### 3. Software assistants with a mascot (Taby and similar)

- **Taby** (heytaby.com): the closest reference and already cited in ADR 0001. A small critter at the top of the Mac/Windows screen that:
  - plans the day on top of your calendar (Google, Outlook or Apple);
  - triages the inbox ("3 emails need you");
  - does smart search over files and photos, dictation and voice;
  - closes distractions.

  The AI runs **locally** and works with Wi-Fi off. It asks for no account. It is free, with a cloud Premium at EUR 8.99/month. There is also a physical "build your own" **Taby**, and users already connect Taby to other agents through a local MCP.
- **Toby, DeskFerry and similar:** Mac assistants with no character, focused on email, calendar and automation.
- **Desktop pets with an LLM:** Nibbii (in the MacBook notch), Desktop Pet, PetClaw, DumbPet, Your Friendly AI, Ollama Pet, PawPal. Many are open source or made by indie devs. Usually a character on screen with chat, sometimes with a Pomodoro timer and reminders.

**Pattern:** Taby proves that "critter + usefulness + local privacy" is a proposal people want, and its community reacts strongly to the cute and physical side. Desktop pets are many and shallow: chat with a skin.

### 4. Open source on ESP32 (the same hardware as Lupin's Body)

- **xiaozhi-esp32** (MIT license): voice chatbot firmware for ESP32, with over 170 releases and a huge community. It talks to LLMs (Qwen, DeepSeek), has an offline wake word and controls devices through **MCP**. It is the strongest technical reference for Lupin's ESP32 firmware.
- **StackChan** (M5Stack, ESP32-S3): a small desk robot with a screen, camera and servos, open source, with an "AI Agent", animations and OTA. Some variants use only local STT, LLM and TTS services.

**Pattern:** the "ESP32 that talks to an LLM" part has become a commodity. The differentiator is not there.

### 5. Ambitions and niches

- **Razer Project AVA:** a holographic companion in a jar, expected in late 2026.
- **ElliQ:** a companion for older adults.
- **Friend:** a pendant that listens to everything, the most controversial on privacy.

## Where Lupin fits

Lupin sits at the intersection almost nobody occupies: the **character with a physical body** of groups 1 and 4, the **real usefulness on the computer** of groups 2 and 3, and an **explicit privacy control**.

| | Companion robots | Autonomous Lamp | Taby | xiaozhi/StackChan | **Lupin** |
|---|---|---|---|---|---|
| Character with Mood/memory | ✅ | partial | ✅ (light) | partial | ✅ (Mood, Affinity, Energy) |
| Physical body | ✅ | ✅ | DIY | ✅ | ✅ ESP32 + RG406H |
| Acts on the computer | ❌ | ✅ (agents) | ✅ | via MCP | ✅ Shortcuts, Dock, Cowork |
| Choice of LLM | ❌/partial | ✅ | local + cloud | ✅ | ✅ (Ollama, OpenAI, Gemini...) |
| Works offline | Eilik/Moflin | ❌ | ✅ | depends | ❌ (not yet) |
| Per-provider data consent | ❌ | ❌ | "nothing leaves" | ❌ | ✅ (Data Consent) |
| Several devices, one character | ❌ | ❌ | ❌ | ❌ | ✅ (Active Body) |
| Price | US$ 140-430 | US$ 699 | free / EUR 9 | ~US$ 30-100 | cheap hardware |

### Lupin's real differentiators

1. **Brain separate from Body, with its own protocol.** A single Lupin can live on several devices (ESP32, RG406H, mini-pet on the Mac) without appearing on two at once, and you can talk to him from any device. No competitor does this.
2. **Risk-based approval for actions.** Cowork Tasks with read/write/external levels, and Shortcut writes only on the Mac. Safer than "the agent does everything".
3. **Concrete privacy.** Calendar and email leave only with Data Consent for a named provider, and the consent drops by itself if the provider changes.
4. **A Today that doesn't make things up.** First Wake is deterministic and does not go through an LLM. It is a direct answer to the hallucination problem almost every assistant has.
5. **Local expression on the Body.** The Body animates on its own and the Brain only sends the Expression. For the same reason that made you reject pixel streaming, the animation stays alive on bad Wi-Fi.

### Gaps compared with the market

- **Offline:** Taby works without Wi-Fi. Lupin depends on the provider (the default is the local proxy, which forwards to the cloud) and on server-side TTS. A 100% local mode (Ollama + local STT/TTS) would be a strong argument.
- **Microphone and camera on the Body:** EMO, Loona and StackChan listen and see through their own bodies. Lupin listens through the Mac.
- **Movement:** Lupin doesn't move physically. This is a conscious choice (ADR 0001), but it is worth owning it in the presentation.
- **Skills and MCP ecosystem:** the Lamp and xiaozhi open up to external agents through MCP. Exposing Lupin as an MCP server (or consuming MCP) would fit him into that ecosystem.
- **Installation:** competitors work out of the box. Lupin today requires server setup, certificates and so on.

## For the portfolio

What this project demonstrates, and is worth highlighting:

- **A genuinely distributed architecture:** Brain/Body, a versioned WebSocket protocol (`docs/brain-body-protocol.md`), Active Body routing and response mirroring.
- **Documented decisions:** ADRs with rejected options and the reason, plus a domain glossary. Few people show this in a personal project.
- **Security and privacy as a requirement:** `subprocess` with a whitelist, no secrets in logs, Data Consent tied to the provider, Mac-only writes.
- **Tests:** Python and frontend suites, with TDD on recent features.
- **Hardware + web + LLM in the same project:** ESP32 firmware (LVGL), a web Body on the RG406H and Electron on the Mac.

Presentation suggestions:

1. **A 60-90 s video** showing First Wake on the ESP32, you talking through the RG406H and Lupin answering on the ESP32, and a Shortcut acting on the Mac. In this market, everyone sells through video.
2. **A showcase README:** a GIF of Lupin, the Brain/Body diagram, the comparison table above (short version) and the three differentiators.
3. **Use Autonomous's three-question test** as the hook: "a companion that passes the working-robot test, at a fraction of the price".
4. **A technical post** about one specific problem: "why Today doesn't use an LLM" or "how a character lives on several devices without duplicating itself".

## Sources

- [Best AI Desk Robots in 2026: Companions vs Work Bots (Autonomous)](https://www.autonomous.ai/ourblog/best-ai-desk-robots)
- [Best AI Companion Robots 2026 (Robot Review Desk)](https://robotreviewdesk.com/guides/best-ai-companion-robots-2026/)
- [AI Companion Robots in 2026 (PocketAnimus)](https://pocketanimus.com/guides/ai-companion-robots/)
- [Taby (heytaby.com)](https://www.heytaby.com)
- [xiaozhi-esp32 (GitHub)](https://github.com/78/xiaozhi-esp32)
- [StackChan (M5Stack docs)](https://docs.m5stack.com/en/StackChan/)
- Search for desktop pets with an LLM: Nibbii, Desktop Pet, PetClaw, Ollama Pet, PawPal (DuckDuckGo results)
