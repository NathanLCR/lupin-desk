# Dictation

Tap the dictate button on the Body, speak, tap again: the text is pasted into the focused Mac app.

## Flow

1. Body (`static/dictation.js`) records the Mac microphone and sends `dictation_start`; Lupin shows the `listening` state.
2. On the second tap it sends `dictation_stop` with the base64 audio (`mime_type`, optional `language`).
3. The Brain (`app/dictation.py`) transcribes locally with mlx-whisper (audio never leaves the Mac), applies the rules below, and calls `MacController.paste_text`: previous clipboard read, text set with `pbcopy`, Cmd+V keystroke, previous clipboard restored (text clipboards only).
4. Brain replies `{"type":"dictation","status":"done|empty|error",...}`. `dictation_cancel` aborts.

The messages are plain WS types for now; they can move to action IDs once Panels P01 lands. Pasting needs the Accessibility permission (`needs_accessibility` is reported).

## Rules (`app/dictation_rules.py`)

- Spoken punctuation, per language (pt-BR / English): comma, period/full stop (`ponto final`), question mark, exclamation, colon, semicolon, new line, new paragraph, open/close parenthesis. A bare `ponto` is not a command.
- Correction: "scratch that" / "apaga isso" removes the previous sentence.
- Spacing is normalised; the first letter and the letter after `. ? !` or a newline are capitalised.
- The language comes from the message, otherwise the STT language setting (pt by default).
