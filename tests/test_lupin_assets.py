"""Ensures Lupin's expressions -> layers table only points to SVGs that exist."""
import json
from pathlib import Path

LUPIN = Path(__file__).resolve().parent.parent / "static" / "lupin"
TABLE = json.loads((LUPIN / "expressions.json").read_text(encoding="utf-8"))
EMOTIONS = [
    "neutral", "happy", "excited", "curious", "skeptical", "surprised",
    "sad", "wink", "love", "sleepy", "angry", "dizzy",
]


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
    assert {"sing", "meditate", "celebrate"} <= set(TABLE["tricks"])


def test_art_carries_no_code_or_external_images():
    for svg in LUPIN.rglob("*.svg"):
        text = svg.read_text(encoding="utf-8").lower()
        for forbidden in ("<script", "<image", "<foreignobject", "http://", "href="):
            if forbidden == "http://":
                text = text.replace("http://www.w3.org/2000/svg", "")
            assert forbidden not in text, f"{svg}: {forbidden}"


def test_blink_and_speech_point_to_poses_that_exist():
    poses = set(TABLE["layers"]["pose"])
    for source, target in TABLE["blink"].items():
        assert source in poses and target in poses, (source, target)
    assert TABLE["blink"], "Lupin must blink from the neutral pose"
    assert TABLE["speech"]["pose"] in poses
