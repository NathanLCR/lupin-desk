# 11 - Fully local mode

Status: needs-triage

## Context

The market survey (`docs/pesquisa-de-mercado.md`) found that Taby works with Wi-Fi off: its LLM, speech-to-text and voice all run on the computer. Lupin depends on the chosen LLM provider (the default local proxy forwards to the cloud) and on server-side TTS. ADR 0001 says offline operation is not a requirement for now. This issue records the gap so it isn't lost. It does not reopen the ADR.

## Scope (to be refined in triage)

- Ollama as the LLM, with speech-to-text and TTS that run on the Mac.
- What Lupin does when a piece is missing (for example, a local model that is too slow).
- How Data Consent interacts with it. Today Ollama gets no exception.

## Open questions

- Is a fully local mode worth it for daily use, or only as a portfolio claim? Per ADR 0001, only daily use counts.
- Which local STT and TTS keep Lupin's voice good enough?

Comes after 03. Do not start without revisiting ADR 0001.
