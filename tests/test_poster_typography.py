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
    FontStack,
    TypeScale,
    covers,
    load_emoji_face,
    load_face,
    measure_runs,
    split_runs,
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
        self.stack = TypeScale(150.0).stack("body")

    def test_blank_line_between_paragraphs_is_kept(self):
        lines = wrap_paragraphs("First para.\n\nSecond para.", self.stack, 10_000)
        assert lines == ["First para.", "", "Second para."]

    def test_single_newlines_start_a_new_line(self):
        lines = wrap_paragraphs("Line one\nLine two", self.stack, 10_000)
        assert lines == ["Line one", "Line two"]

    def test_long_paragraph_wraps_within_the_width(self):
        text = " ".join(["word"] * 50)
        lines = wrap_paragraphs(text, self.stack, 300)
        assert len(lines) > 1
        for line in lines:
            assert measure_runs(split_runs(line, self.stack)) <= 300

    def test_trailing_blank_lines_are_dropped(self):
        lines = wrap_paragraphs("Only para.\n\n\n", self.stack, 10_000)
        assert lines == ["Only para."]

    def test_a_word_longer_than_the_line_is_not_dropped(self):
        lines = wrap_paragraphs("supercalifragilistic", self.stack, 5)
        assert lines == ["supercalifragilistic"]


class TestFontAvailability:
    def test_a_real_truetype_face_is_bundled(self):
        """Guard rail. If the bundled face can't be found or loaded, the render
        silently drops to Pillow's bitmap default — which has no bold weight
        and no usable cmap, so the *symptom* is unrelated-looking failures
        elsewhere (glyph stripping quietly turning itself off, flat type).
        Fail here instead, where the cause is obvious."""
        from PIL.ImageFont import FreeTypeFont

        for weight in ("regular", "medium", "bold"):
            assert isinstance(load_face(weight, 20), FreeTypeFont), (
                f"no TrueType face resolved for '{weight}' — check assets/fonts/"
            )


class TestEmojiFallback:
    """Emoji are *rendered*, not suppressed, when an emoji face is available.

    Pillow performs no font fallback of its own, so mixed text has to be split
    into runs and each drawn with the face that covers it. These cover that
    segmentation; the drawing itself is exercised in test_poster_renderer.
    """

    def setup_method(self):
        self.scale = TypeScale(150.0)
        self.stack = self.scale.stack("body")

    def test_an_emoji_face_is_bundled(self):
        assert load_emoji_face(17) is not None, (
            "no emoji face resolved - check assets/fonts/NotoColorEmoji.ttf"
        )

    def test_emoji_survive_when_an_emoji_face_is_present(self):
        text = "Sunrise 🏔 ridge 🎒"
        assert strip_unsupported(text, self.stack) == text

    def test_emoji_are_dropped_when_only_a_text_face_is_available(self):
        """Graceful degradation: with no emoji face, dropping them still beats
        printing .notdef boxes."""
        text_only = FontStack(faces=(self.scale.font("body"),), size_px=17)
        assert strip_unsupported("Sunrise 🏔 ridge", text_only) == "Sunrise ridge"

    def test_text_and_emoji_are_split_into_separate_runs(self):
        runs = split_runs("Hi 🏔 there", self.stack)
        assert [r.text for r in runs] == ["Hi ", "🏔", " there"]
        assert not runs[0].scaled and not runs[2].scaled
        assert runs[1].face is not self.stack.primary

    def test_a_pure_text_string_stays_one_unscaled_run(self):
        runs = split_runs("no emoji here", self.stack)
        assert len(runs) == 1
        assert not runs[0].scaled

    def test_measuring_pure_text_matches_single_face_measurement(self):
        """Routing text through the stack must not change ordinary layout."""
        text = "Sunrise ridge done"
        assert measure_runs(split_runs(text, self.stack)) == pytest.approx(
            _measure(text, self.scale.font("body"))
        )

    def test_emoji_advance_is_close_to_the_text_size(self):
        """A fixed-strike bitmap face renders at 109px; without the per-run
        scale an emoji would advance several times the text size and wreck
        both wrapping and alignment."""
        run = split_runs("🏔", self.stack)[0]
        assert self.stack.size_px <= run.advance <= self.stack.size_px * 2

    def test_whitespace_is_measured_in_the_text_face(self):
        """A space swept into an emoji run would be measured at the emoji
        face's native size and come out far too wide."""
        for run in split_runs("a 🏔 b", self.stack):
            if run.text.strip() == "":
                assert not run.scaled

    def test_variation_selector_16_forces_the_emoji_presentation(self):
        """U+2744 has a monochrome glyph in DejaVu, so the text face would
        claim it; U+FE0F explicitly asks for the colour emoji form."""
        plain = split_runs("❄", self.stack)
        emoji = split_runs("❄️", self.stack)
        assert not plain[0].scaled, "bare U+2744 should stay in the text face"
        assert emoji[0].scaled, "U+2744 U+FE0F should use the emoji face"

    def test_presentation_marks_survive_stripping(self):
        """Regression: strip_unsupported runs *before* split_runs, and no face
        has a visible glyph for U+FE0F, so an earlier version stripped it — the
        selector never reached the code that acts on it and colour-requested
        emoji silently fell back to the monochrome text glyph."""
        text = "Snow " + chr(0x2744) + chr(0xFE0F)
        assert chr(0xFE0F) in strip_unsupported(text, self.stack)

    def test_selector_still_forces_emoji_after_a_strip_pass(self):
        """The end-to-end ordering the card layout actually uses."""
        text = "Snow " + chr(0x2744) + chr(0xFE0F)
        runs = split_runs(strip_unsupported(text, self.stack), self.stack)
        assert any(r.scaled for r in runs), "colour presentation was lost"

    def test_characters_no_face_covers_are_still_dropped(self):
        # Neither DejaVu nor Noto Color Emoji covers CJK.
        assert strip_unsupported("ok 中 ok", self.stack) == "ok ok"

    def test_accented_latin_is_preserved(self):
        text = "Café Zürich Ångström"
        assert strip_unsupported(text, self.stack) == text

    def test_typographic_punctuation_is_preserved(self):
        text = "Day 3 — the col – done"
        assert strip_unsupported(text, self.stack) == text

    def test_plain_ascii_is_untouched(self):
        assert strip_unsupported("plain ascii text", self.stack) == "plain ascii text"

    def test_paragraph_breaks_survive(self):
        text = "One " + chr(0x1F3D4) + chr(10) + chr(10) + "Two"
        assert strip_unsupported(text, self.stack) == text

    def test_empty_input_is_safe(self):
        assert strip_unsupported("", self.stack) == ""
