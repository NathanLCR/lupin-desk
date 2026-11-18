"""Turn a raw Whisper dictation transcript into the final text to paste.

Pure functions only: no I/O and no state kept between calls.

Rules, applied in this order:

1. Corrections: "scratch that" (en) and "apaga isso" / "apague isso" (pt)
   delete the phrase and the sentence before it, back to the previous
   . ? ! or newline (or the start of the text). Processed left to right.
2. Spoken punctuation: whole-word phrases become symbols ("comma" -> ",")
   together with the Whisper punctuation directly adjacent to them, so
   "hello, comma, how" becomes "hello, how". Longer phrases match first.
3. Spacing: no space before , . ; : ? ! ) and none after (; exactly one
   space after , . ; : ? ! when a word follows on the same line; no spaces
   around newlines; repeated spaces collapsed; result stripped. A "." ","
   or ":" between two digits is left alone, so "3.14" and "10:30" survive.
4. Capitalisation: the first letter of the text and the first letter after
   ". ", "? ", "! " or a newline are upper-cased. Nothing else changes case.

Language: the first two letters of `language` pick the table ("pt-BR" uses
pt, "en-US" uses en). Any other language uses both tables.
"""

from __future__ import annotations

import functools
import re

_CORRECTIONS: dict[str, tuple[str, ...]] = {
    "en": ("scratch that",),
    "pt": ("apaga isso", "apague isso"),
}

_SPOKEN: dict[str, dict[str, str]] = {
    "en": {
        "question mark": "?",
        "exclamation mark": "!",
        "exclamation point": "!",
        "full stop": ".",
        "period": ".",
        "comma": ",",
        "semicolon": ";",
        "colon": ":",
        "new paragraph": "\n\n",
        "new line": "\n",
        "open parenthesis": "(",
        "close parenthesis": ")",
    },
    "pt": {
        "ponto de interrogação": "?",
        "interrogação": "?",
        "ponto de exclamação": "!",
        "exclamação": "!",
        "ponto final": ".",
        "vírgula": ",",
        "ponto e vírgula": ";",
        "dois pontos": ":",
        "novo parágrafo": "\n\n",
        "nova linha": "\n",
        "abre parênteses": "(",
        "fecha parênteses": ")",
    },
}

_ADJACENT_PUNCT = r"[,.;:!?]"
_SENTENCE_END = ".?!\n"


def _language_codes(language: str) -> tuple[str, ...]:
    code = (language or "").strip().lower()[:2]
    if code in _SPOKEN:
        return (code,)
    return tuple(_SPOKEN)


def _phrase_regex(phrase: str) -> str:
    # Whitespace inside a phrase matches any run of whitespace.
    return r"\s+".join(re.escape(word) for word in phrase.split())


def _sorted_longest_first(phrases) -> list[str]:
    return sorted(phrases, key=len, reverse=True)


@functools.lru_cache(maxsize=None)
def _correction_pattern(codes: tuple[str, ...]) -> re.Pattern[str]:
    phrases = {p for code in codes for p in _CORRECTIONS[code]}
    alternation = "|".join(_phrase_regex(p) for p in _sorted_longest_first(phrases))
    return re.compile(
        rf"(?<!\w)(?:{alternation})(?!\w)[.!?,;:]*",
        re.IGNORECASE,
    )


@functools.lru_cache(maxsize=None)
def _spoken_table(codes: tuple[str, ...]) -> dict[str, str]:
    table: dict[str, str] = {}
    for code in codes:
        table.update(_SPOKEN[code])
    return table


@functools.lru_cache(maxsize=None)
def _spoken_pattern(codes: tuple[str, ...]) -> re.Pattern[str]:
    phrases = _sorted_longest_first(_spoken_table(codes))
    alternation = "|".join(_phrase_regex(p) for p in phrases)
    return re.compile(
        rf"(?:{_ADJACENT_PUNCT}[ \t]*)?"
        rf"(?<!\w)(?P<phrase>{alternation})(?!\w)"
        rf"(?:{_ADJACENT_PUNCT})?",
        re.IGNORECASE,
    )


def _apply_corrections(text: str, codes: tuple[str, ...]) -> str:
    pattern = _correction_pattern(codes)
    while True:
        match = pattern.search(text)
        if match is None:
            return text
        cut = max(text.rfind(mark, 0, match.start()) for mark in _SENTENCE_END) + 1
        text = text[:cut] + text[match.end():]


def _apply_spoken_punctuation(text: str, codes: tuple[str, ...]) -> str:
    table = _spoken_table(codes)

    def replace(match: re.Match[str]) -> str:
        key = " ".join(match.group("phrase").lower().split())
        return table[key]

    return _spoken_pattern(codes).sub(replace, text)


def _space_after_mark(match: re.Match[str]) -> str:
    text = match.string
    mark = match.group(1)
    if mark in ".,:" and match.start() > 0:
        before = text[match.start() - 1]
        after = text[match.end()]
        if before.isdigit() and after.isdigit():
            return match.group(0)
    return f"{mark} "


def _normalise_spacing(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r" ([,.;:?!)])", r"\1", text)
    text = re.sub(r"\( ", "(", text)
    text = re.sub(r"([,.;:?!]) ?(?=\w)", _space_after_mark, text)
    return text.strip()


_CAPITALISE = re.compile(r"(^[^\w]*|[.?!]\s+|\n\s*)([^\W\d_])")


def _capitalise(text: str) -> str:
    return _CAPITALISE.sub(lambda m: m.group(1) + m.group(2).upper(), text)


def apply_dictation_rules(text: str, language: str = "pt") -> str:
    """Return the final text to paste for a raw Whisper transcript."""
    if not text or not text.strip():
        return ""
    codes = _language_codes(language)
    result = _apply_corrections(text, codes)
    result = _apply_spoken_punctuation(result, codes)
    result = _normalise_spacing(result)
    return _capitalise(result).strip()
