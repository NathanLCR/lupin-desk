# 15 - Lupin's language setting

Status: ready-for-agent (after 14)

## Context

Decided on 2026-11-17. The project is in English, but what Lupin says follows a user setting, Brazilian Portuguese by default.

## Spec

- Two languages: Brazilian Portuguese (default) and English.
- The setting lives in Settings → Voice and sound and can be changed from **any device** (unlike Shortcuts and Data Consent, which are Mac-only).
- One setting drives everything Lupin speaks and hears:
  - the reply language in the system prompt;
  - the First Wake sentences, and any other canned speech;
  - the TTS voice (a voice that matches the language);
  - the language the Mac listens for (speech-to-text).
- Switching takes effect on the next turn; nothing already said is re-spoken.
- The setting is saved on the Brain, so every Body sees the same value.

## Acceptance criteria

- [ ] With English selected, First Wake, replies, voice and listening are in English; with PT-BR, they are as today.
- [ ] Changing the setting from the RG406H works (no 403).
- [ ] Tests cover First Wake in both languages and that the system prompt asks for the chosen language.
