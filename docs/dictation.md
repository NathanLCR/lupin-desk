# Dictation (Lupin issue 07)

Speak, and the text appears in the Mac's focused app.

## Flow

1. Turn on **Dictation** (button next to the mic button). Touching Lupin now means "type".
2. Touch the Body: Lupin shows the `listening` Expression and the Mac's microphone records.
3. Touch the Body again: recording stops and the audio goes to the Brain with `dictation: true`.
4. The Brain transcribes it with local mlx-whisper (audio never leaves the Mac), applies the rules
   below, puts the text on the clipboard, presses Cmd+V in the focused app, then restores the
   previous clipboard. No LLM is involved.
5. The caption says what happened (`dictation_result`: inserted, nothing heard, paste failed, or
   Accessibility permission needed). Wording lives in `app/speech_en.py` / `app/speech_pt_br.py`.

Limits: the previous clipboard is restored only when it was text (an image or files on the
clipboard are replaced). Pasting needs the macOS Accessibility permission.

## Text rules (`app/dictation.py`)

Spoken punctuation (language follows the STT language, pt-BR or English):

| Say (pt-BR) | Say (English) | Result |
|---|---|---|
| vírgula | comma | `,` |
| ponto final | period, full stop | `.` |
| ponto de interrogação | question mark | `?` |
| ponto de exclamação | exclamation mark/point | `!` |
| dois pontos | colon | `:` |
| ponto e vírgula | semicolon | `;` |
| nova linha | new line | line break |
| novo parágrafo | new paragraph | blank line |
| abre / fecha parênteses | open / close parenthesis | `(` `)` |

Correction: saying `apaga isso` / `esquece isso` (English: `scratch that` / `delete that`) drops the
sentence dictated just before it.

Cleanup: no space before a mark, one space after; repeated marks collapse; the first letter, the
letter after `. ! ?` and the letter after a line break are capitalised. Marks Whisper already
wrote are kept.
