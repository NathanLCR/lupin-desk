"""Tests for the dictation post-processing rules in app/dictation_rules.py."""

from __future__ import annotations

import pytest

from app.dictation_rules import apply_dictation_rules


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("one comma two", "One, two"),
        ("one semicolon two", "One; two"),
        ("one colon two", "One: two"),
        ("one full stop", "One."),
        ("one period", "One."),
        ("is it true question mark", "Is it true?"),
        ("wow exclamation mark", "Wow!"),
        ("wow exclamation point", "Wow!"),
        ("one open parenthesis x close parenthesis", "One (x)"),
    ],
)
def test_english_spoken_punctuation(raw: str, expected: str) -> None:
    assert apply_dictation_rules(raw, "en") == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("oi ponto de interrogação", "Oi?"),
        ("oi interrogação", "Oi?"),
        ("uau ponto de exclamação", "Uau!"),
        ("uau exclamação", "Uau!"),
        ("um ponto final", "Um."),
        ("um vírgula dois", "Um, dois"),
        ("um ponto e vírgula dois", "Um; dois"),
        ("um dois pontos dois", "Um: dois"),
        ("um abre parênteses x fecha parênteses", "Um (x)"),
    ],
)
def test_portuguese_spoken_punctuation(raw: str, expected: str) -> None:
    assert apply_dictation_rules(raw, "pt") == expected


def test_bare_ponto_is_not_mapped_in_portuguese() -> None:
    assert apply_dictation_rules("um ponto dois", "pt") == "Um ponto dois"


def test_longest_match_wins() -> None:
    # "ponto e vírgula" must become ";" and not "." followed by a stray ",".
    assert apply_dictation_rules("a ponto e vírgula b", "pt") == "A; b"
    assert apply_dictation_rules("a vírgula b", "pt") == "A, b"


def test_whisper_punctuation_next_to_spoken_word_is_absorbed() -> None:
    raw = "hello, comma, how are you question mark"
    assert apply_dictation_rules(raw, "en") == "Hello, how are you?"


def test_spoken_word_inside_other_word_is_not_mapped() -> None:
    assert apply_dictation_rules("a commander b", "en") == "A commander b"


def test_new_line_and_new_paragraph_english() -> None:
    assert apply_dictation_rules("one new line two", "en") == "One\nTwo"
    assert apply_dictation_rules("hello new paragraph how are you", "en") == (
        "Hello\n\nHow are you"
    )


def test_new_line_and_new_paragraph_portuguese() -> None:
    assert apply_dictation_rules("um nova linha dois", "pt") == "Um\nDois"
    assert apply_dictation_rules("oi novo parágrafo tudo bem", "pt") == (
        "Oi\n\nTudo bem"
    )


def test_newline_drops_spaces_around_it() -> None:
    assert apply_dictation_rules("a  new line   b", "en") == "A\nB"


def test_scratch_that_deletes_previous_sentence_en() -> None:
    raw = "Buy milk. Call mom scratch that. Buy eggs"
    assert apply_dictation_rules(raw, "en") == "Buy milk. Buy eggs"


def test_scratch_that_without_boundary_deletes_whole_prefix() -> None:
    assert apply_dictation_rules("Hello there scratch that", "en") == ""


def test_scratch_that_is_case_insensitive_and_takes_trailing_punctuation() -> None:
    raw = "Buy milk. Call mom Scratch That! Buy eggs"
    assert apply_dictation_rules(raw, "en") == "Buy milk. Buy eggs"


@pytest.mark.parametrize("phrase", ["apaga isso", "apague isso"])
def test_apaga_isso_deletes_previous_sentence_pt(phrase: str) -> None:
    raw = f"Compre leite. Ligue pra mãe {phrase}. Compre ovos"
    assert apply_dictation_rules(raw, "pt") == "Compre leite. Compre ovos"


def test_multiple_corrections_are_applied_left_to_right() -> None:
    raw = "A. B scratch that. C. D scratch that."
    assert apply_dictation_rules(raw, "en") == "A. C."


def test_correction_phrase_is_not_applied_in_other_language() -> None:
    assert apply_dictation_rules("Hello scratch that", "pt") == "Hello scratch that"


def test_capitalises_after_period() -> None:
    assert apply_dictation_rules("first sentence. second sentence", "en") == (
        "First sentence. Second sentence"
    )


def test_capitalises_after_question_and_exclamation() -> None:
    assert apply_dictation_rules("is it? yes! ok", "en") == "Is it? Yes! Ok"


def test_does_not_lowercase_other_letters() -> None:
    assert apply_dictation_rules("the iPhone is great. NASA rocks", "en") == (
        "The iPhone is great. NASA rocks"
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("pi is 3.14 ok", "Pi is 3.14 ok"),
        ("at 10:30 now", "At 10:30 now"),
        ("costs 3,5 dollars", "Costs 3,5 dollars"),
    ],
)
def test_digits_keep_their_separators(raw: str, expected: str) -> None:
    assert apply_dictation_rules(raw, "en") == expected


def test_spacing_is_normalised() -> None:
    assert apply_dictation_rules("hello   world ,next", "en") == "Hello world, next"
    assert apply_dictation_rules("hello.world", "en") == "Hello. World"


@pytest.mark.parametrize("raw", ["", "   ", "\n\t "])
def test_empty_or_whitespace_input_returns_empty_string(raw: str) -> None:
    assert apply_dictation_rules(raw, "pt") == ""


def test_pt_br_selects_portuguese_table() -> None:
    assert apply_dictation_rules("oi vírgula tudo", "pt-BR") == "Oi, tudo"
    assert apply_dictation_rules("hello comma world", "pt-BR") == "Hello comma world"


def test_en_us_selects_english_table() -> None:
    assert apply_dictation_rules("hello comma world", "en-US") == "Hello, world"
    assert apply_dictation_rules("oi vírgula tudo", "en-US") == "Oi vírgula tudo"


@pytest.mark.parametrize("language", ["fr", "de-DE", "", "xx"])
def test_unknown_language_uses_both_tables(language: str) -> None:
    assert apply_dictation_rules("hello comma world", language) == "Hello, world"
    assert apply_dictation_rules("oi vírgula tudo", language) == "Oi, tudo"
    assert apply_dictation_rules("Hello scratch that", language) == ""
    assert apply_dictation_rules("Oi apaga isso", language) == ""
