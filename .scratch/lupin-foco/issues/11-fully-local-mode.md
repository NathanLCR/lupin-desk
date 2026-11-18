# 11 - Fully local mode

Status: done (Kokoro install and live voice check pending)

## Context

The market survey (`docs/market-research.md`) found that Taby works with Wi-Fi off: its LLM, speech-to-text and voice all run on the computer. Lupin depends on the chosen LLM provider (the default local proxy forwards to the cloud) and on server-side TTS. ADR 0001 says offline operation is not a requirement for now. This issue records the gap so it isn't lost. It does not reopen the ADR.

## Scope (to be refined in triage)

- Ollama as the LLM, with speech-to-text and TTS that run on the Mac.
- What Lupin does when a piece is missing (for example, a local model that is too slow).
- How Data Consent interacts with it. Today Ollama gets no exception.

## Open questions

- Is a fully local mode worth it for daily use, or only as a portfolio claim? Per ADR 0001, only daily use counts.
- Which local STT and TTS keep Lupin's voice good enough?

Comes after 03. Do not start without revisiting ADR 0001.

## Decisions (grill 2026-11-18)

- Built this push. Ollama becomes a provider in Settings. STT is already local (whisper).
- Kokoro becomes Lupin's TTS everywhere (local and cloud modes), in pt-BR and English; macOS `say` stays as the fallback.
- Ollama runs on the Mac, so it needs no Data Consent.
- When a local model is slow, Lupin shows a thinking Expression and says so.
- ADR 0002 revisits ADR 0001 for this issue; offline operation is possible, still not required.
