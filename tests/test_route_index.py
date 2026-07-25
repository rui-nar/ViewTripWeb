"""Tests for src/poster/route_index.py (issue #14 feedback).

Pure geometry, no Pillow/DB/network. The point of this index is to let card
placement ask "would this card sit on the track?" cheaply and correctly, so the
tests cover both the correctness of the intersection predicates and the fact
that bucketing doesn't lose segments.
"""
from __future__ import annotations

from src.poster.route_index import RouteIndex, _segment_intersects_rect, _segments_cross


class TestSegmentIntersection:
    def test_crossing_segments_intersect(self):
        assert _segments_cross((0, 0, 10, 10), (0, 10, 10, 0))

    def test_parallel_segments_do_not_intersect(self):
        assert not _segments_cross((0, 0, 10, 0), (0, 5, 10, 5))

    def test_touching_endpoint_counts_as_intersecting(self):
        assert _segments_cross((0, 0, 5, 5), (5, 5, 10, 0))

    def test_disjoint_segments_do_not_intersect(self):
        assert not _segments_cross((0, 0, 1, 1), (100, 100, 101, 101))


class TestSegmentVsRect:
    RECT = (100.0, 100.0, 200.0, 200.0)  # left, top, right, bottom

    def test_segment_wholly_inside_rect_hits(self):
        assert _segment_intersects_rect((120, 120, 180, 180), *self.RECT)

    def test_segment_crossing_straight_through_hits(self):
        assert _segment_intersects_rect((0, 150, 400, 150), *self.RECT)

    def test_segment_clipping_one_corner_hits(self):
        assert _segment_intersects_rect((150, 50, 250, 150), *self.RECT)

    def test_segment_passing_well_clear_misses(self):
        assert not _segment_intersects_rect((0, 400, 400, 400), *self.RECT)

    def test_segment_alongside_but_outside_misses(self):
        assert not _segment_intersects_rect((0, 0, 400, 0), *self.RECT)

    def test_segment_whose_bbox_overlaps_but_line_misses(self):
        """A diagonal whose bounding box covers the rect but which passes
        outside its corner must not count as a hit — the cheap bbox reject
        alone would get this wrong."""
        assert not _segment_intersects_rect((0, 300, 300, 0), 10.0, 10.0, 60.0, 60.0)


class TestRouteIndex:
    def test_empty_index_is_falsey_and_never_intersects(self):
        index = RouteIndex([], (1000, 1000))
        assert not index
        assert not index.intersects_rect(0, 0, 1000, 1000)

    def test_single_point_polyline_contributes_no_segments(self):
        index = RouteIndex([[(5, 5)]], (100, 100))
        assert not index

    def test_zero_length_segments_are_discarded(self):
        index = RouteIndex([[(5, 5), (5, 5), (5, 5)]], (100, 100))
        assert not index

    def test_finds_a_segment_anywhere_on_a_long_track(self):
        """Bucketing must not lose segments: probe every span of a long track."""
        track = [(x, 500) for x in range(0, 2000, 7)]
        index = RouteIndex([track], (2000, 2000))
        for x in range(20, 1900, 137):
            assert index.intersects_rect(x - 5, 495, x + 5, 505), f"missed track near x={x}"

    def test_rect_between_two_track_passes_is_clear(self):
        lines = [[(x, 100) for x in range(0, 1000, 5)],
                 [(x, 900) for x in range(0, 1000, 5)]]
        index = RouteIndex(lines, (1000, 1000))
        assert not index.intersects_rect(400, 400, 600, 600)
        assert index.intersects_rect(400, 50, 600, 150)

    def test_crosses_segment_detects_a_leader_cutting_the_track(self):
        index = RouteIndex([[(x, 500) for x in range(0, 1000, 5)]], (1000, 1000))
        assert index.crosses_segment(400, 400, 400, 600), "vertical line must cross"
        assert not index.crosses_segment(400, 100, 600, 200), "both ends above the track"

    def test_results_match_a_brute_force_scan(self):
        """The grid is an optimisation; it must agree with checking every
        segment directly."""
        import random

        rng = random.Random(20260725)
        lines = [
            [(rng.uniform(0, 800), rng.uniform(0, 800)) for _ in range(40)]
            for _ in range(6)
        ]
        index = RouteIndex(lines, (800, 800))

        for _ in range(200):
            left = rng.uniform(0, 700)
            top = rng.uniform(0, 700)
            rect = (left, top, left + rng.uniform(5, 90), top + rng.uniform(5, 90))
            brute = any(_segment_intersects_rect(seg, *rect) for seg in index.segments)
            assert index.intersects_rect(*rect) == brute, f"disagreement on {rect}"
