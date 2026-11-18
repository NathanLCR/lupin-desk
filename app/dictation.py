"""Dictation text rules: spoken punctuation, a spoken correction and capitalisation.

Pure functions, no I/O. The words are the user's dictation vocabulary, not what Lupin says, so
they live here and not in the speech tables. Rules are documented in `docs/dictation.md`.
"""

from __future__ import annotations

import re

# Spoken phrase -> text to insert. Longer phrases first inside each language so that
# "ponto e vírgula" wins over "ponto final". Brackets come first so that a mark spoken
# right after them ("close parenthesis period") is not swallowed.
_PUNCTUATION: dict[str, tuple[tuple[str, str], ...]] = {
    "en": (
        ("open parenthesis", "("),
        ("close parenthesis", ")"),
        ("new paragraph", "\n\n"),
        ("new line", "\n"),
        ("question mark", "?"),
        ("exclamation mark", "!"),
        ("exclamation point", "!"),
        ("semicolon", ";"),
        ("full stop", "."),
        ("period", "."),
        ("colon", ":"),
        ("comma", ","),
    ),
    "pt": (
        ("abre parênteses", "("),
        ("fecha parênteses", ")"),
        ("novo parágrafo", "\n\n"),
        ("nova linha", "\n"),
        ("ponto de interrogação", "?"),
        ("ponto de exclamação", "!"),
        ("ponto e vírgula", ";"),
        ("ponto final", "."),
        ("dois pontos", ":"),
        ("vírgula", ","),
    ),
}

# Spoken correction: drops the sentence dictated just before it.
_SCRATCH = {
    "en": ("scratch that", "delete that"),
    "pt": ("apaga isso", "esquece isso"),
}

_TRAILING_MARK = r"[,.;:!?]?"


def _lang_key(language: str | None) -> str:
    return "pt" if str(language or "pt").strip().lower().startswith("pt") else "en"


def _phrase_re(phrase: str) -> str:
    return r"(?<!\w)" + r"\s+".join(re.escape(w) for w in phrase.split()) + r"(?!\w)"


def _apply_scratch(text: str, lang: str) -> str:
    pattern = re.compile(
        "(?:" + "|".join(_phrase_re(p) for p in _SCRATCH[lang]) + ")" + _TRAILING_MARK,
        re.IGNORECASE,
    )
    while True:
        match = pattern.search(text)
        if not match:
            return text
        before = text[: match.start()].rstrip()
        # Drop the last sentence: keep everything up to the previous sentence end.
        if before and before[-1] in ".!?":
            before = before[:-1]
        cut = max(before.rfind("."), before.rfind("!"), before.rfind("?"), before.rfind("\n"))
        kept = before[: cut + 1] if cut >= 0 else ""
        text = kept + " " + text[match.end() :]


def format_dictation(raw: str, language: str | None = "pt-BR") -> str:
    """Turn a raw recognition result into the text to insert.

    Applies, in order: spoken correction, spoken punctuation, spacing around punctuation and
    capitalisation (start of text, after . ! ? and after a new line). Returns "" when nothing
    is left (so the caller inserts nothing).
    """
    text = str(raw or "").strip()
    if not text:
        return ""
    lang = _lang_key(language)

    text = _apply_scratch(text, lang)

    rules = sorted(_PUNCTUATION[lang], key=lambda rule: "\n" in rule[1])  # new lines last
    for phrase, symbol in rules:
        # Whisper often adds its own mark next to the word ("Vírgula,"): absorb it.
        pattern = re.compile(
            r"[ \t]*" + _phrase_re(phrase) + _TRAILING_MARK + r"[ \t]*", re.IGNORECASE
        )
        if symbol == "(":
            replacement = " ("
        elif symbol in ("\n", "\n\n"):
            replacement = symbol
        else:
            replacement = symbol + " "
        text = pattern.sub(lambda _m, r=replacement: r, text)

    text = re.sub(r"([,.;:!?])(?:\s*\1)+", r"\1", text)  # "oi,, " -> "oi,"
    text = re.sub(r"[ \t]+([,.;:!?)])", r"\1", text)  # no space before a mark
    text = re.sub(r"\(\s+", "(", text)  # none after "("
    text = re.sub(r"([,;:!?)])(?=[^\W\d_])", r"\1 ", text)  # a space after a mark, before a word
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text).strip()

    def _cap(match: re.Match[str]) -> str:
        return match.group(1) + match.group(2).upper()

    return re.sub(r"((?:^|[.!?]\s+|\n)[(]?)([^\W\d_])", _cap, text)
