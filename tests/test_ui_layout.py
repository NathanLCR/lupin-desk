"""Regressões estruturais de layout e acessibilidade da interface estática."""

from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


class MarkupIndex(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.elements = []
        self.labels_for = set()
        self.label_depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "label":
            self.label_depth += 1
            if attrs.get("for"):
                self.labels_for.add(attrs["for"])
        self.elements.append({"tag": tag, "attrs": attrs, "inside_label": self.label_depth > 0})

    def handle_endtag(self, tag):
        if tag == "label" and self.label_depth:
            self.label_depth -= 1


def css_block(css, marker):
    start = css.index(marker)
    opening = css.index("{", start)
    depth = 1
    for end in range(opening + 1, len(css)):
        if css[end] == "{":
            depth += 1
        elif css[end] == "}":
            depth -= 1
            if depth == 0:
                return css[opening + 1 : end]
    raise AssertionError(f"Bloco CSS sem fechamento: {marker}")


MARKUP = MarkupIndex()
MARKUP.feed(HTML)
BY_ID = {
    element["attrs"].get("id"): element
    for element in MARKUP.elements
    if element["attrs"].get("id")
}


def test_required_page_landmarks_and_locale_remain():
    assert '<html lang="pt-BR">' in HTML
    assert '<main id="stage"' in HTML
    assert '<header id="hud" class="hud" aria-label="Controles superiores"' in HTML
    assert 'content="width=device-width, initial-scale=1.0, viewport-fit=cover"' in HTML


def test_each_mode_has_a_descriptive_accessible_name():
    modes = {
        element["attrs"].get("data-mode"): element["attrs"]
        for element in MARKUP.elements
        if element["tag"] == "button" and element["attrs"].get("data-mode")
    }
    for mode in ("pet", "dock", "nathan"):
        assert modes[mode].get("aria-label")
        assert modes[mode].get("title")
        assert "aria-pressed" in modes[mode]


def test_status_and_caption_are_polite_atomic_live_regions():
    for element_id in ("ws-status", "caption-box"):
        attrs = BY_ID[element_id]["attrs"]
        assert attrs.get("role") == "status"
        assert attrs.get("aria-live") == "polite"
        assert attrs.get("aria-atomic") == "true"


def test_visible_form_controls_have_programmatic_names():
    controls = (
        element
        for element in MARKUP.elements
        if element["tag"] in {"input", "select", "textarea"}
    )
    for element in controls:
        attrs = element["attrs"]
        if attrs.get("type") == "hidden":
            continue
        control_id = attrs.get("id")
        named = any(attrs.get(key) for key in ("aria-label", "aria-labelledby"))
        named = named or element["inside_label"] or control_id in MARKUP.labels_for
        assert named, f"Controle de formulário sem rótulo acessível: {control_id}"


def test_fixed_workspace_reserves_space_below_the_hud_and_chat():
    workspace = css_block(CSS, ".workspace-panel")
    assert "var(--hud-offset)" in workspace
    assert "var(--dock-clearance)" in workspace
    tablet = css_block(CSS, "@media (max-width: 1024px)")
    phone = css_block(CSS, "@media (max-width: 740px)")
    assert "--hud-offset: 120px" in tablet
    assert "--hud-offset: 192px" in phone
    assert "overflow-y: auto" in workspace
    assert "overscroll-behavior: contain" in workspace
    for clearance in ("174px", "144px", "234px"):
        assert f"--dock-clearance: {clearance}" in CSS


def test_handheld_form_text_stays_at_ios_zoom_safe_size():
    handheld = css_block(CSS, "@media (max-width: 1024px)")
    assert 'input:not([type="checkbox"]):not([type="radio"])' in handheld
    assert "select," in handheld and "textarea" in handheld
    assert "font-size: 16px" in handheld


def test_keyboard_focus_and_small_viewport_targets_are_present():
    assert "):focus-visible" in CSS
    assert "outline: 2px solid var(--accent-cyan)" in CSS
    tablet = css_block(CSS, "@media (max-width: 1024px)")
    assert "button," in tablet and "min-height: 44px" in tablet
    assert "min-height: 44px" in tablet[tablet.index(".hud-btn {") :]
    assert 'role="img" aria-label="Rosto animado de Lupin"' in HTML


def test_existing_dom_ids_remain_unique():
    ids = [element["attrs"]["id"] for element in MARKUP.elements if "id" in element["attrs"]]
    assert len(ids) == len(set(ids))
