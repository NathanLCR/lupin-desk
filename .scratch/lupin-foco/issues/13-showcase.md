# 13 - Showcase: README, video and opening the repo

Status: needs-triage

## Context

The project is for daily use and also a portfolio piece (ADR 0001, 2026-11-17 addendum: the portfolio gets presentation only, never features). The current README is out of date: it still sells the "Stream Deck" and "Dock Viva", which ADR 0001 cut.

## Scope (to be refined in triage)

- Rewrite the README in English as the showcase. It should open with the positioning, "a desk companion that actually works", and carry the Brain/Body diagram, the differentiators and a short comparison table from `docs/pesquisa-de-mercado.md`.
- A 60–90 s video: the First Wake on the ESP32, speaking from the RG406H with Lupin answering on the ESP32, and a Shortcut acting on the Mac. Until the ESP32 arrives, leave a placeholder.
- Before the repo is ever made public, audit the whole git history for secrets and personal data (`.env`, keys, emails, Cowork paths, `data/`). Making the repo public stays the user's decision, and pushing stays forbidden until then.
- Optional: a technical write-up, e.g. why Today doesn't use an LLM, or how one character lives in several devices without duplicating.

Starts after 03 is done. The video waits for the ESP32.
