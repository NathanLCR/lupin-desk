# 13 - Showcase: v0.1 public release (README, media, opening the repo)

Status: ready-for-agent (triaged 2026-11-18 by the product owner session)

## Context

The project is for daily use and also a portfolio piece (ADR 0001, 2026-11-17 addendum: the portfolio gets presentation only, never features). The goal of v0.1 is a public GitHub repo (`NathanLCR/lupin-desk`, already created **public and empty**) that a recruiter or engineer can understand in 60 seconds, plus a LinkedIn post that links to it.

## Product-owner review (2026-11-18)

**What's strong and goes in the story:**
- Two pillars that work today: Lupin (Brain on the Mac, web Body on the RG406H, Mac mini-pet) and Panels (Layouts, widgets, Mac Layout editor, Android kiosk shell, E-ink Mode, Signals).
- A clear position from market research: "a desk companion that actually works".
- Engineering discipline: ~750 Python tests and ~450 frontend tests, ADRs, a glossary, a security baseline (argv whitelists, secret redaction, Data Consent), and a measured write-up on building with AI agents (`docs/agent-workflow-report.md`).

**What blocked a release:**
- The README is out of date. It sells the Stream Deck, Live Dock and "Screen Modes" that ADR 0001 cut, and it hardcodes personal paths and IPs.
- No LICENSE.
- A first push to the public repo would publish superseded Portuguese docs (`docs/superpowers/`) and agent handoff scratch notes.
- One failing frontend test, a log filter that crashed uvicorn's access log, and a hardcoded `/Users/...` default path. **Fixed 2026-11-18.**

## Decisions (user, 2026-11-18)

- **LAN trust stays** (ADR 0002). The README gets a "Security model" section saying this is a single-user home-LAN project, and spelling out the risk (anyone on the Wi-Fi can view Panels and send Panel actions, including Allow on a Claude Code prompt). No code change.
- **Curated public tree.** Keep `docs/adr/`, `GLOSSARY.md`, `AGENTS.md`, `docs/*.md`, `.scratch/lupin-foco/` and `.scratch/panels/` (specs and issues show the process) and `docs/agent-workflow-report.md`. Remove `docs/superpowers/` (superseded, Portuguese) and the agent scratch notes (`.scratch/agents/*handoff*`, `.scratch/research/`, `.scratch/reviews/`). History keeps them; history was audited and has no real secrets (only fake test keys like `freellmapi-test-secret-123`).
- **License: MIT.**
- **Media: screenshots/GIF only for v0.1.** The video waits for the ESP32 (v0.2).

## v0.1 release checklist

- [x] Fix the failing frontend test, the log filter crash and the personal default path; extend `.gitignore`.
- [x] `LICENSE` (MIT, Nathan Rocha, 2026).
- [x] Remove the curated-out files from the tree.
- [x] Rewrite `README.md` in English as the showcase (structure below).
- [x] Screenshots in `docs/media/`: Lupin's face and the Mac Layout editor. Follow-up: a populated demo Layout (no personal data) for better Panel and E-ink shots.
- [ ] All tests green; server restarted and checked live.
- [ ] Commit on `lupin-foco`, merge into `main`, tag `v0.1.0`. *(user's go-ahead)*
- [ ] First push to `NathanLCR/lupin-desk`; set the description and topics; create the GitHub release. *(user's go-ahead: pushing publishes)*
- [ ] LinkedIn post (draft provided, the user posts it).

### README structure

1. Title, one-line positioning, hero screenshot, badges (tests, license).
2. What it is: the two pillars in a few sentences, plus "where it sits" (the short comparison table from `docs/market-research.md`).
3. Architecture: a Brain/Body/Panels diagram (Mermaid) and the single-WebSocket protocol.
4. Features that exist today (honest about what's device-tested and what isn't).
5. Quick start: Mac, `.env`, run the Brain, open a Body or a Panel.
6. Security model and Data Consent.
7. How it was built: ADRs, the spec-then-code gate, the agent-workflow findings.
8. Roadmap: ESP32 Body, P08–P10 widgets, Presence, Image editor.
9. License.

## Out of scope for v0.1

The ESP32 firmware, P08–P10, issues 04 and 08, and any feature work. Device tests marked "pending" in the specs are listed as known limitations, not blockers.
