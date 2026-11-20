"""Ensures Lupin's expressions -> layers table only points to SVGs that exist."""
import json
from pathlib import Path

LUPIN = Path(__file__).resolve().parent.parent / "static" / "lupin"
TABLE = json.loads((LUPIN / "expressions.json").read_text(encoding="utf-8"))
EMOTIONS = [
    "neutral", "happy", "excited", "curious", "skeptical", "surprised",
    "sad", "wink", "love", "sleepy", "angry", "dizzy",
]
EXPECTED_LAYERS = [
    "tail", "torso", "collar", "head", "ear-left", "ear-right", "eyes", "mouth",
]


def test_version_three_structure_and_pivots():
    assert TABLE["version"] == 3
    assert TABLE["layerOrder"] == EXPECTED_LAYERS
    assert list(TABLE["layers"]) == EXPECTED_LAYERS
    assert TABLE["headGroup"] == ["head", "ear-left", "ear-right", "eyes", "mouth"]
    for key in ("breath", "headGroup", "ear-left", "ear-right", "tail"):
        coords = TABLE["pivots"][key]
        assert len(coords) == 2
        assert 0 <= coords[0] <= 480 and 0 <= coords[1] <= 320


def test_every_table_variant_has_a_480x320_svg():
    for layer, variants in TABLE["layers"].items():
        for variant in variants:
            svg = LUPIN / "layers" / layer / f"{variant}.svg"
            assert svg.is_file(), f"missing {svg}"
            assert 'width="480" height="320"' in svg.read_text(encoding="utf-8"), svg


def test_no_orphan_svg_outside_the_table():
    expected = {
        LUPIN / "layers" / layer / f"{v}.svg"
        for layer, variants in TABLE["layers"].items()
        for v in variants
    }
    for trick in TABLE["tricks"].values():
        for frame in trick.get("frames", []):
            expected.add(LUPIN / "body" / f"{frame}.svg")
    assert set(LUPIN.rglob("*.svg")) == expected


def test_twelve_expressions_and_five_states_use_valid_variants():
    assert set(TABLE["expressions"]) == set(EMOTIONS)
    assert set(TABLE["states"]) == {"idle", "listening", "thinking", "speaking", "error"}
    for source in (*TABLE["expressions"].values(), *TABLE["states"].values()):
        for layer, variant in source.items():
            if layer in TABLE["layers"]:
                assert variant in TABLE["layers"][layer], (layer, variant)


def test_full_body_tricks_are_only_dance_stretch_and_nap():
    body = {name for name, t in TABLE["tricks"].items() if t["mode"] == "body"}
    assert body == {"dance", "stretch", "nap"}
    assert TABLE["tricks"]["dance"]["frames"] == ["dance-1", "dance-2"]
    assert {"sing", "meditate", "celebrate"} <= set(TABLE["tricks"])


def test_art_carries_no_code_or_external_images():
    for svg in LUPIN.rglob("*.svg"):
        text = svg.read_text(encoding="utf-8").lower()
        for forbidden in ("<script", "<image", "<foreignobject", "http://", "href="):
            if forbidden == "http://":
                text = text.replace("http://www.w3.org/2000/svg", "")
            assert forbidden not in text, f"{svg}: {forbidden}"


def test_blink_and_speech_point_to_valid_eye_and_mouth_variants():
    eyes = set(TABLE["layers"]["eyes"])
    mouths = set(TABLE["layers"]["mouth"])
    for source, target in TABLE["blink"].items():
        assert source in eyes and target in eyes, (source, target)
    assert {"open", "curious", "skeptical", "surprised", "sad", "angry"} <= set(TABLE["blink"])

    speech = TABLE["speech"]
    assert speech["closed"] in mouths
    levels = speech["levels"]
    assert len(levels) >= 2
    assert [lvl["minLevel"] for lvl in levels] == sorted((lvl["minLevel"] for lvl in levels), reverse=True)
    for lvl in levels:
        assert lvl["mouth"] in mouths
