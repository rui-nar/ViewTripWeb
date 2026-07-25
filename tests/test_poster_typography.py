"""Tests for src/poster/typography.py (issue #14 feedback).

The complaint these cover: "there's no formatting of the text with hero and
different fonts". The old renderer used Pillow's built-in default font at three
pixel sizes, so there was no bold, no hierarchy, and text shrank relative to the
page as resolution rose.
"""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from src.poster.typography import (
    TYPE_SCALE,
    TypeScale,
    load_face,
    strip_unsupported,
    wrap_paragraphs,
)

_MEASURE_CTX = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def _measure(text, font):
    return _MEASURE_CTX.textlength(text, font=font)


class TestPhysicalSizing:
    def test_point_sizes_convert_to_pixels_by_dpi(self):
        """8pt is the agreed body size: ~17px at 150 DPI, ~33px at 300."""
        assert TypeScale(150.0).px(8.0) == 17
        assert TypeScale(300.0).px(8.0) == 33

    def test_the_same_style_doubles_in_pixels_when_dpi_doubles(self):
        for name in TYPE_SCALE:
            at_150 = TypeScale(150.0).px(TYPE_SCALE[name].size_pt)
            at_300 = TypeScale(300.0).px(TYPE_SCALE[name].size_pt)
            assert at_300 == pytest.approx(at_150 * 2, abs=1), name

    def test_line_height_exceeds_the_font_size(self):
        scale = TypeScale(150.0)
        for name in TYPE_SCALE:
            assert scale.line_height(name) >= scale.px(TYPE_SCALE[name].size_pt)


class TestHierarchy:
    def test_hero_title_is_larger_than_body_which_is_larger_than_label(self):
        scale = TypeScale(150.0)
        hero = scale.px(scale.style("hero_title").size_pt)
        title = scale.px(scale.style("title").size_pt)
        body = scale.px(scale.style("body").size_pt)
        label = scale.px(scale.style("label").size_pt)
        assert hero > title > body > label

    def test_headings_are_bold_and_body_is_not(self):
        assert TYPE_SCALE["hero_title"].weight == "bold"
        assert TYPE_SCALE["title"].weight == "bold"
        assert TYPE_SCALE["stat_value"].weight == "bold"
        assert TYPE_SCALE["body"].weight == "regular"

    def test_bold_and_regular_resolve_to_visually_different_faces(self):
        """The whole point of bundling a real font: the old default face had
        no bold, so every card rendered as one flat weight."""
        bold = load_face("bold", 40)
        regular = load_face("regular", 40)
        assert _measure("Handgloves", bold) > _measure("Handgloves", regular)

    def test_muted_styles_are_lighter_than_ink_styles(self):
        assert TYPE_SCALE["date"].color != TYPE_SCALE["body"].color
        assert sum(TYPE_SCALE["date"].color) > sum(TYPE_SCALE["body"].color)

    def test_captions_are_uppercased_and_values_are_not(self):
        scale = TypeScale(150.0)
        assert scale.prepare("label", "Coffees") == "COFFEES"
        assert scale.prepare("date", "14 Jul 2026") == "14 JUL 2026"
        assert scale.prepare("body", "Mixed Case") == "Mixed Case"


class TestParagraphPreservingWrap:
    def setup_method(self):
        self.font = TypeScale(150.0).font("body")

    def test_blank_line_between_paragraphs_is_kept(self):
        lines = wrap_paragraphs("First para.\n\nSecond para.", self.font, 10_000, _measure)
        assert lines == ["First para.", "", "Second para."]

    def test_single_newlines_start_a_new_line(self):
        lines = wrap_paragraphs("Line one\nLine two", self.font, 10_000, _measure)
        assert lines == ["Line one", "Line two"]

    def test_long_paragraph_wraps_within_the_width(self):
        text = " ".join(["word"] * 50)
        lines = wrap_paragraphs(text, self.font, 300, _measure)
        assert len(lines) > 1
        for line in lines:
            assert _measure(line, self.font) <= 300

    def test_trailing_blank_lines_are_dropped(self):
        lines = wrap_paragraphs("Only para.\n\n\n", self.font, 10_000, _measure)
        assert lines == ["Only para."]

    def test_a_word_longer_than_the_line_is_not_dropped(self):
        lines = wrap_paragraphs("supercalifragilistic", self.font, 5, _measure)
        assert lines == ["supercalifragilistic"]


class TestGlyphStripping:
    def setup_method(self):
        self.font = TypeScale(150.0).font("body")

    def test_emoji_are_removed(self):
        # Emoji have no glyph in Inter or DejaVu; Pillow would draw .notdef
        # boxes, which is what made cards look garbled.
        assert strip_unsupported("Sunrise \U0001F3D4 ridge \U0001F392", self.font) == "Sunrise ridge"

    def test_accented_latin_is_preserved(self):
        text = "Café Zürich Ångström"
        assert strip_unsupported(text, self.font) == text

    def test_typographic_punctuation_is_preserved(self):
        text = "Day 3 — the col – done"
        assert strip_unsupported(text, self.font) == text

    def test_plain_ascii_is_untouched(self):
        assert strip_unsupported("plain ascii text", self.font) == "plain ascii text"

    def test_paragraph_breaks_survive_stripping(self):
        out = strip_unsupported("One \U0001F3D4\n\nTwo", self.font)
        assert out == "One\n\nTwo"

    def test_empty_input_is_safe(self):
        assert strip_unsupported("", self.font) == ""
