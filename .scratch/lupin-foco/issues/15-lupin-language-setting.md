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

- [x] With English selected, First Wake, replies, voice and listening are in English; with PT-BR, they are as today.
- [x] Changing the setting from the RG406H works (no 403).
- [x] Tests cover First Wake in both languages and that the system prompt asks for the chosen language.

## Done

- `app/speech_en.py` (sibling of `speech_pt_br.py`, same names) and `app/speech.py` (selector: `set_language`, `for_language`, attribute access resolves against the current language).
- Setting saved in `app_meta` (`lupin_language`), default `pt-BR`; `GET/PUT /api/lupin-language` (any device, no 403; 422 for unsupported values). Loaded at `create_app`, so it survives restarts.
- Drives: system prompt and every canned sentence (First Wake, mood, temporal, consent, Today fallbacks, LLM error); server TTS voice (`TTS_VOICE` for pt-BR, `TTS_VOICE_EN`, default Samantha, for English); STT default language for `/api/stt` and WS audio (an explicit client `language` still wins); web Body voice/locale, Pomodoro end phrases and diagnostics test phrases.
- UI: Settings -> Voice and sound -> "Lupin's language" select; clients fetch the value on load and on each WebSocket connect.
- Out of scope, left as is: the fact-extraction regexes in `app/memory.py` (Portuguese only), the seeded Shortcut titles and voice triggers.
- Tests: `tests/test_lupin_language.py`.
