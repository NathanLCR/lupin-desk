# v0.1 launch kit (issue 13)

## GitHub repo settings (NathanLCR/lupin-desk)

- **Description:** Lupin, a desk companion that actually works. A Mac "Brain" (FastAPI + LLM + memory + voice) drives a husky that lives on an old handheld, and turns old phones, tablets and a Kindle into desk panels.
- **Topics:** `desk-companion`, `fastapi`, `websocket`, `llm`, `voice-assistant`, `macos`, `android`, `e-ink`, `kindle`, `home-dashboard`, `ai-agents`, `esp32`
- **Release:** tag `v0.1.0`, title "v0.1: Lupin and Panels". Body: the Features section of the README plus "Known limitations: device tests pending on some Panels; the ESP32 Body arrives in v0.2."

## LinkedIn post (draft, in English; the user edits and posts it)

I built a desk companion that actually does work.

Lupin is a husky who lives on an old Anbernic handheld on my desk. The "brain" runs on my Mac: an LLM with long-term memory, a mood, local voice, and permission to act on the Mac through a strict whitelist. You talk, he answers with a face and a voice, and he can start a Pomodoro, run a shortcut or tell you what's on today.

The second half of the project turns old devices into desk panels: an Android 7 phone, an iPad, a laptop and even a Kindle in e-ink mode, all fed by one WebSocket protocol and laid out in a browser editor on the Mac.

What I'm proudest of is how it was built:
• Architecture Decision Records and a glossary before code
• A "spec, then code" rule: every feature is grilled and specced first, then built by AI agents, then reviewed by a fresh agent
• I measured it: one Sonnet builder per issue used about 4× fewer tokens than a nested Opus → Sonnet → Haiku team, and the independent reviewer caught blocking bugs in 6 of 9 issues, including a remote-code-execution hole
• ~1,200 automated tests (Python + JS)

Next up: an ESP32 touchscreen body for Lupin.

Code and write-up: https://github.com/NathanLCR/lupin-desk

#BuildInPublic #AI #Python #FastAPI #AIagents #SideProject

(Attach 2–3 images from `docs/media/`: Lupin's face, a Panel, the e-ink Kindle page.)
