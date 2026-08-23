"""Tests for src/poster/card_layout.py (issue #14 feedback).

The complaint these cover: "the cards have fixed sizes and don't resize
according to the content that is selected". Cards are now measured from their
content, so the tests assert relationships (more content => taller card) rather
than pixel-exact heights, which would be brittle against font metrics.

No filesystem access: photo lookup is injected.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.poster.card_layout import (
    CARD_MAX_HEIGHT_MM,
    CARD_PADDING_MM,
    MAX_DESCRIPTION_LINES,
    PhotoOp,
    RuleOp,
    TextOp,
    card_min_height_px,
    card_width_px,
    layout_card,
    mm_to_px,
)
from src.poster.typography import TypeScale


@pytest.fixture
def scale():
    return TypeScale(150.0)


def _name(text="Col du Galibier"):
    return {"kind": "name", "text": text}


def _date(text="14 Jul 2026"):
    return {"kind": "date", "text": text}


def _desc(text="A long climb in the afternoon sun, switchback after switchback."):
    return {"kind": "description", "text": text}


def _ops(layout, kind):
    return [op for op in layout.ops if isinstance(op, kind)]


class TestContentDrivenHeight:
    def test_more_content_makes_a_taller_card(self, scale):
        minimal = layout_card([_name(), _date()], scale)
        with_desc = layout_card([_name(), _date(), _desc()], scale)
        with_stats = layout_card(
            [_name(), _date(), _desc(),
             {"kind": "distance", "value_m": 84210.0},
             {"kind": "elevation", "value_m": 2100.0}],
            scale,
        )

        assert minimal.height < with_desc.height < with_stats.height

    def test_longer_description_makes_a_taller_card(self, scale):
        short = layout_card([_name(), _desc("One line.")], scale)
        long = layout_card([_name(), _desc(" ".join(["word"] * 60))], scale)
        assert long.height > short.height

    def test_card_width_is_uniform_regardless_of_content(self, scale):
        """Height varies with content; width deliberately does not, so the
        poster reads as a composition rather than a ragged pile."""
        a = layout_card([_name()], scale)
        b = layout_card([_name(), _date(), _desc()], scale)
        assert a.width == b.width == card_width_px(scale.dpi)

    def test_empty_content_still_yields_a_minimum_sized_card(self, scale):
        """The degenerate case — every content flag off — must still be a real,
        positively-sized rectangle rather than a zero/negative one."""
        layout = layout_card([], scale)
        assert layout.height == card_min_height_px(scale)
        assert layout.height > 0
        assert layout.ops == []

    def test_the_minimum_height_is_padding_plus_one_line_of_text(self, scale):
        """The floor is derived from the layout's own metrics, not a fixed
        number: two paddings plus one line of the smallest text role."""
        assert card_min_height_px(scale) == (
            2 * mm_to_px(CARD_PADDING_MM, scale.dpi) + scale.line_height("label")
        )

    def test_a_sparse_card_is_far_shorter_than_the_old_26mm_floor(self, scale):
        """Regression coverage for "shrink to content": a card carrying only a
        date used to be padded out to a flat 26mm, which is about four lines of
        body copy, so every sparse card looked deliberately boxy."""
        old_floor = mm_to_px(26.0, scale.dpi)
        assert layout_card([_date()], scale).height < old_floor
        assert layout_card([], scale).height < old_floor

    def test_a_date_only_card_is_shorter_than_a_date_plus_name_card(self, scale):
        """Sparse content genuinely shrinks now instead of hitting a floor that
        made both cards identical."""
        assert layout_card([_date()], scale).height < layout_card(
            [_name(), _date()], scale).height

    def test_height_is_capped_so_one_memory_cannot_dominate_the_poster(self, scale):
        huge = layout_card(
            [_name(), _desc(" ".join(["elaboration"] * 4000))]
            + [{"kind": "counters", "items": [{"name": f"c{i}", "value": i} for i in range(200)]}],
            scale,
        )
        assert huge.height <= mm_to_px(CARD_MAX_HEIGHT_MM, scale.dpi)

    def test_description_is_truncated_rather_than_growing_without_bound(self, scale):
        layout = layout_card([_desc(" ".join(["word"] * 400))], scale)
        body_lines = [op for op in _ops(layout, TextOp) if op.style == "body"]
        assert len(body_lines) <= MAX_DESCRIPTION_LINES
        assert body_lines[-1].text.endswith("…"), "truncated text should be marked"


class TestPhysicalScaling:
    def test_card_geometry_scales_with_dpi(self):
        """The same card must occupy the same *physical* area at any DPI, so
        pixel dimensions scale with the render resolution."""
        blocks = [_name(), _date(), _desc()]
        at_150 = layout_card(blocks, TypeScale(150.0))
        at_300 = layout_card(blocks, TypeScale(300.0))

        assert at_300.width == pytest.approx(at_150.width * 2, rel=0.02)
        assert at_300.height == pytest.approx(at_150.height * 2, rel=0.05)


class TestBlockRendering:
    def test_name_and_date_produce_distinct_styles(self, scale):
        layout = layout_card([_name(), _date()], scale)
        styles = {op.style for op in _ops(layout, TextOp)}
        assert "date" in styles
        assert styles & {"title", "hero_title"}, "the name must use a heading style"

    def test_a_text_only_card_uses_the_larger_hero_title(self, scale):
        layout = layout_card([_name()], scale)
        assert {op.style for op in _ops(layout, TextOp)} == {"hero_title"}

    def test_a_card_led_by_a_photo_demotes_the_name_to_title(self, scale):
        layout = layout_card(
            [{"kind": "hero_photo", "uuid": "u1"}, _name()], scale,
            photo_path=lambda uuid: Path("photo.jpg"),
        )
        text_styles = {op.style for op in _ops(layout, TextOp)}
        assert text_styles == {"title"}, (
            "a hero image already carries the emphasis; the name should not "
            "also be set at hero size"
        )

    def test_stats_draw_a_separating_rule(self, scale):
        layout = layout_card(
            [_name(), {"kind": "distance", "value_m": 1000.0}], scale)
        assert _ops(layout, RuleOp), "stats should be separated by a hairline rule"

    def test_stats_never_overlap_horizontally(self, scale):
        """Three stats whose values are too wide to sit side by side must
        stack instead of colliding."""
        layout = layout_card(
            [{"kind": "distance", "value_m": 128_400.0},
             {"kind": "elevation", "value_m": 12_100.0},
             {"kind": "encounters", "count": 17}],
            scale,
        )
        values = [op for op in _ops(layout, TextOp) if op.style == "stat_value"]
        assert len(values) == 3
        by_row = {}
        for op in values:
            by_row.setdefault(op.y, []).append(op)
        for row in by_row.values():
            # Anything sharing a row must start at a distinct x.
            xs = sorted(op.x for op in row)
            assert len(set(xs)) == len(xs)

    def test_counters_render_as_label_value_rows(self, scale):
        layout = layout_card(
            [{"kind": "counters", "items": [{"name": "Coffees", "value": 11}]}], scale)
        texts = [op.text for op in _ops(layout, TextOp)]
        assert "COFFEES" in texts, "counter labels are uppercased by the type scale"
        assert "11" in texts


class TestPhotos:
    def test_hero_photo_spans_the_content_width(self, scale):
        layout = layout_card(
            [{"kind": "hero_photo", "uuid": "u1"}], scale,
            photo_path=lambda uuid: Path("x.jpg"),
        )
        photos = _ops(layout, PhotoOp)
        assert len(photos) == 1
        pad = mm_to_px(4.0, scale.dpi)
        assert photos[0].w == layout.width - 2 * pad
        assert photos[0].h > 0

    def test_missing_photo_files_are_skipped_without_reserving_space(self, scale):
        present = layout_card(
            [{"kind": "hero_photo", "uuid": "u1"}, _name()], scale,
            photo_path=lambda uuid: Path("x.jpg"))
        absent = layout_card(
            [{"kind": "hero_photo", "uuid": "u1"}, _name()], scale,
            photo_path=lambda uuid: None)
        assert absent.height < present.height
        assert not _ops(absent, PhotoOp)

    def test_photo_blocks_are_skipped_entirely_without_a_resolver(self, scale):
        layout = layout_card([{"kind": "hero_photo", "uuid": "u1"}], scale)
        assert not _ops(layout, PhotoOp)

    def test_grid_photos_are_uniform_squares(self, scale):
        layout = layout_card(
            [{"kind": "photos", "uuids": [f"u{i}" for i in range(5)]}], scale,
            photo_path=lambda uuid: Path(f"{uuid}.jpg"),
        )
        photos = _ops(layout, PhotoOp)
        assert len(photos) == 5
        assert len({(p.w, p.h) for p in photos}) == 1, "cells must be uniform"
        assert photos[0].w == photos[0].h, "cells must be square"

    def test_hero_photo_is_not_repeated_in_the_grid(self, scale):
        """Showing the hero at full width and again as the first grid cell
        directly beneath it reads as a bug."""
        uuids = ["hero", "b", "c"]
        layout = layout_card(
            [{"kind": "hero_photo", "uuid": "hero"}, {"kind": "photos", "uuids": uuids}],
            scale, photo_path=lambda uuid: Path(f"{uuid}.jpg"),
        )
        photos = _ops(layout, PhotoOp)
        hero_paths = [p for p in photos if p.path == Path("hero.jpg")]
        assert len(hero_paths) == 1
