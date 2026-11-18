"""Language selector for everything Lupin says.

`from app import speech` and then `speech.persona_prompt(...)`, `speech.MOOD_HAPPY`, ... resolve
against the Brain's current language (issue 15): Brazilian Portuguese (default) or English. The
words live in `app/speech_pt_br.py` and `app/speech_en.py`, which share the same public names.
The Brain sets the language at startup (from the saved setting) and when the setting changes, so
a switch takes effect on the next turn.
"""

from __future__ import annotations

from types import ModuleType

from app import speech_en, speech_pt_br

DEFAULT_LANGUAGE = "pt-BR"
SUPPORTED_LANGUAGES: tuple[str, ...] = ("pt-BR", "en")

_MODULES: dict[str, ModuleType] = {"pt-BR": speech_pt_br, "en": speech_en}
_current = DEFAULT_LANGUAGE


def normalize_language(value: object) -> str | None:
    """Map 'pt', 'pt_br', 'EN', ... to a supported code; None when unsupported."""
    key = str(value or "").strip().lower().replace("_", "-")
    if key in ("pt-br", "pt"):
        return "pt-BR"
    if key in ("en", "en-us", "en-gb"):
        return "en"
    return None


def for_language(lang: str | None) -> ModuleType:
    """The speech module for a language code (falls back to the default)."""
    return _MODULES[normalize_language(lang) or DEFAULT_LANGUAGE]


def set_language(lang: str | None) -> str:
    """Make `lang` the current language; returns the normalized code."""
    global _current
    _current = normalize_language(lang) or DEFAULT_LANGUAGE
    return _current


def get_language() -> str:
    return _current


def __getattr__(name: str):
    if name.startswith("__"):
        raise AttributeError(name)
    return getattr(_MODULES[_current], name)
