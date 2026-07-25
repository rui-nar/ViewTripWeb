"""Tests for the poster card-placement algorithm (issue #14, unit C).

Covers the invariants the caller (renderer) relies on:
  - placed cards never overlap each other and stay within canvas bounds
  - placement is deterministic across runs
  - pins that can't fit a card anywhere within the search radius are
    reported as overflow (placed=False), never silently dropped or
    force-overlapped
  - a lone pin gets a sensible non-overlapping card
  - cards avoid covering the trip's own track, and leader lines land on a
    card's border rather than its centre (issue #14 feedback)
  - each pin's card uses that pin's own measured size
"""

from __future__ import annotations

from datetime import date

import pytest

from src.poster.card_placement import CardPlacement, PinSpec, Rect, place_cards
from src.poster.route_index import RouteIndex


def _rects_overlap(a: Rect, b: Rect) -> bool:
    return a.overlaps(b)


def _placed_rects(results: list[CardPlacement]) -> list[Rect]:
    return [r.card_rect for r in results if r.placed]


class TestNoOverlapInvariant:
    def test_sparse_pins_all_placed_without_overlap(self):
        pins = [
            PinSpec(id=f"p{i}", x=x, y=y, sort_key=date(2025, 6, 1 + i), size=(120, 80))
            for i, (x, y) in enumerate(
                [(200, 200), (800, 200), (200, 800), (800, 800), (500, 500)]
            )
        ]
        results = place_cards(pins, canvas_size=(1200, 1200))

        assert len(results) == len(pins)
        rects = _placed_rects(results)
        assert len(rects) == len(pins), "sparse pins should all get a card"

        for rect in rects:
            assert rect.within((1200, 1200))

        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not _rects_overlap(rects[i], rects[j]), (
                    f"cards for pin {i} and {j} overlap: {rects[i]} vs {rects[j]}"
                )

    def test_dense_cluster_placed_cards_never_overlap(self):
        # 12 pins packed within a tight 40x40 box: some will overflow, but
        # whichever ones do get a card must never overlap another.
        pins = [
            PinSpec(id=f"c{i}", x=500 + (i % 4) * 10, y=500 + (i // 4) * 10,
                    sort_key=date(2025, 7, 1 + i), size=(100, 60))
            for i in range(12)
        ]
        results = place_cards(pins, canvas_size=(2000, 2000))

        assert len(results) == 12
        rects = _placed_rects(results)
        for rect in rects:
            assert rect.within((2000, 2000))
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not _rects_overlap(rects[i], rects[j])

    def test_gutter_is_respected_between_cards(self):
        pins = [
            PinSpec(id="a", x=400, y=400, sort_key=1, size=(100, 60)),
            PinSpec(id="b", x=460, y=400, sort_key=2, size=(100, 60)),
        ]
        results = place_cards(pins, canvas_size=(2000, 2000), gutter=20)
        rects = _placed_rects(results)
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                # Inflating one rect by the gutter must still not overlap.
                assert not rects[i].overlaps(rects[j], 20)


class TestDeterminism:
    def test_same_input_yields_identical_output(self):
        pins = [
            PinSpec(id=f"p{i}", x=300 + (i % 5) * 15, y=300 + (i // 5) * 15,
                    sort_key=date(2025, 1, 1 + i), size=(90, 50))
            for i in range(20)
        ]
        first = place_cards(pins, canvas_size=(1500, 1500))
        second = place_cards(pins, canvas_size=(1500, 1500))

        assert first == second

    def test_determinism_survives_unsorted_input_order(self):
        pins = [
            PinSpec(id="a", x=100, y=100, sort_key=date(2025, 3, 3), size=(80, 40)),
            PinSpec(id="b", x=110, y=100, sort_key=date(2025, 3, 1), size=(80, 40)),
            PinSpec(id="c", x=100, y=110, sort_key=date(2025, 3, 2), size=(80, 40)),
        ]
        first = place_cards(pins, canvas_size=(1000, 1000))
        second = place_cards(list(reversed(pins)), canvas_size=(1000, 1000))

        # Result order follows sort_key (ascending), regardless of input order.
        assert [r.pin_id for r in first] == ["b", "c", "a"]
        assert first == second


class TestLegendFallback:
    def test_overflow_pins_are_marked_not_dropped_or_overlapping(self):
        # 30 pins crammed into a small area with a small canvas: far too
        # dense for every pin to get a non-overlapping card.
        pins = [
            PinSpec(
                id=f"n{i}",
                x=300 + (i % 6) * 5,
                y=300 + (i // 6) * 5,
                sort_key=date(2025, 5, 1 + i),
                size=(150, 100),
            )
            for i in range(30)
        ]
        results = place_cards(pins, canvas_size=(700, 700))

        assert len(results) == 30, "every pin must appear in the output, none dropped"

        overflowed = [r for r in results if not r.placed]
        placed = [r for r in results if r.placed]

        assert len(overflowed) > 0, "cluster should be dense enough to force overflow"
        for r in overflowed:
            assert r.card_rect is None

        rects = [r.card_rect for r in placed]
        for rect in rects:
            assert rect.within((700, 700))
        for i in range(len(rects)):
            for j in range(i + 1, len(rects)):
                assert not _rects_overlap(rects[i], rects[j])

    def test_earlier_sort_key_wins_contested_space(self):
        # Two pins so close together that only one can claim the immediate
        # ring of positions before the other's card would overlap it -- the
        # earlier-dated pin (processed first) should be the one placed if
        # space is tight enough to matter, and no result is ever dropped.
        pins = [
            PinSpec(id="later", x=100, y=100, sort_key=date(2025, 1, 2), size=(60, 40)),
            PinSpec(id="earlier", x=102, y=100, sort_key=date(2025, 1, 1), size=(60, 40)),
        ]
        results = place_cards(pins, canvas_size=(4000, 4000))
        by_id = {r.pin_id: r for r in results}
        # Canvas is huge, so both should actually fit -- this just checks
        # ordering/processing, not forced overflow.
        assert by_id["earlier"].placed
        assert by_id["later"].placed


class TestSanitySinglePin:
    def test_single_pin_gets_card_at_sensible_offset(self):
        pin = PinSpec(id="only", x=500, y=500, sort_key=date(2025, 1, 1), size=(100, 60))
        results = place_cards([pin], canvas_size=(1000, 1000))

        assert len(results) == 1
        result = results[0]
        assert result.placed
        assert result.pin_id == "only"
        rect = result.card_rect
        assert rect is not None
        assert rect.within((1000, 1000))

        # Card must not sit directly on top of the pin: the pin point
        # itself should fall outside the card rectangle.
        assert not rect.contains_point(pin.x, pin.y)

        # Card should be a reasonable distance away, not clear across the canvas.
        cx, cy = rect.center
        dist = ((cx - pin.x) ** 2 + (cy - pin.y) ** 2) ** 0.5
        assert dist < 300


class TestEmptyInput:
    def test_no_pins_returns_empty_list(self):
        assert place_cards([], canvas_size=(1000, 1000)) == []


# ---------------------------------------------------------------------------
# Per-pin card sizes (issue #14 feedback: cards size to their content)
# ---------------------------------------------------------------------------

class TestPerPinCardSize:
    def test_each_card_uses_its_own_pin_size(self):
        pins = [
            PinSpec(id="small", x=300, y=300, sort_key=1, size=(80, 40)),
            PinSpec(id="tall", x=900, y=900, sort_key=2, size=(200, 400)),
        ]
        results = {r.pin_id: r for r in place_cards(pins, canvas_size=(2000, 2000))}

        small = results["small"].card_rect
        tall = results["tall"].card_rect
        assert (small.right - small.left, small.bottom - small.top) == (80, 40)
        assert (tall.right - tall.left, tall.bottom - tall.top) == (200, 400)


# ---------------------------------------------------------------------------
# Route avoidance (issue #14 feedback: "cards keep crossing the track")
# ---------------------------------------------------------------------------

class TestRouteAvoidance:
    # A horizontal track laid across the spot the route-unaware search reaches
    # first (it tries north before anything else), so these two tests form a
    # matched pair: same pin, same track, avoidance on vs off.
    ROUTE_Y = 420
    CANVAS = (2000, 2000)

    def _route(self) -> RouteIndex:
        return RouteIndex([[(x, self.ROUTE_Y) for x in range(0, 2000, 10)]], self.CANVAS)

    def _pin(self) -> PinSpec:
        return PinSpec(id="p", x=1000, y=500, sort_key=1, size=(200, 120))

    def test_without_route_awareness_the_card_lands_on_the_track(self):
        """Control: establishes that this setup really does put the naive
        placement on the track, so the avoidance test below proves something."""
        route = self._route()
        naive = place_cards([self._pin()], canvas_size=self.CANVAS, route=None)[0]
        rect = naive.card_rect
        assert route.intersects_rect(rect.left, rect.top, rect.right, rect.bottom), (
            "expected the route-unaware placement to land on the track; if this "
            "stops holding, the avoidance test below proves nothing"
        )

    def test_card_avoids_a_track_running_beside_the_pin(self):
        route = self._route()
        result = place_cards([self._pin()], canvas_size=self.CANVAS, route=route)[0]

        assert result.placed
        rect = result.card_rect
        assert not route.intersects_rect(rect.left, rect.top, rect.right, rect.bottom), (
            f"card {rect} was placed on top of the track"
        )

    def test_leader_line_does_not_cross_the_track_when_avoidable(self):
        route = self._route()
        result = place_cards([self._pin()], canvas_size=self.CANVAS, route=route)[0]
        pin = self._pin()
        ax, ay = result.anchor
        assert not route.crosses_segment(pin.x, pin.y, ax, ay), (
            "leader line cuts across the track"
        )

    def test_dense_route_still_places_cards_rather_than_overflowing_everything(self):
        """Route avoidance is a strong preference, not a hard veto: a pin
        surrounded by track must still get a card rather than being dumped into
        the legend."""
        lines = [[(x, y) for x in range(0, 1200, 5)] for y in range(0, 1200, 40)]
        route = RouteIndex(lines, (1200, 1200))
        pin = PinSpec(id="p", x=600, y=600, sort_key=1, size=(150, 100))

        result = place_cards([pin], canvas_size=(1200, 1200), route=route)[0]
        assert result.placed, "a card is still better than a legend entry"

    def test_no_route_segments_behaves_like_no_route(self):
        empty = RouteIndex([], (1000, 1000))
        pin = PinSpec(id="p", x=500, y=500, sort_key=1, size=(100, 60))
        with_empty = place_cards([pin], canvas_size=(1000, 1000), route=empty)
        without = place_cards([pin], canvas_size=(1000, 1000), route=None)
        assert with_empty == without


# ---------------------------------------------------------------------------
# Leader anchors
# ---------------------------------------------------------------------------

class TestLeaderAnchor:
    def test_anchor_lies_on_the_card_border_not_its_centre(self):
        pin = PinSpec(id="p", x=500, y=500, sort_key=1, size=(120, 80))
        result = place_cards([pin], canvas_size=(1400, 1400))[0]

        rect = result.card_rect
        ax, ay = result.anchor
        on_vertical_edge = ax in (rect.left, rect.right) and rect.top <= ay <= rect.bottom
        on_horizontal_edge = ay in (rect.top, rect.bottom) and rect.left <= ax <= rect.right
        assert on_vertical_edge or on_horizontal_edge, (
            f"anchor {(ax, ay)} is not on the border of {rect}"
        )
        assert (ax, ay) != rect.center

    def test_anchor_is_the_nearest_border_point_to_the_pin(self):
        rect = Rect(left=100, top=100, right=300, bottom=200)
        # Pin directly left of the rect: nearest border point is on the left
        # edge, at the pin's own y.
        assert rect.edge_anchor(20, 150) == (100, 150)
        # Pin directly above: nearest point is on the top edge at the pin's x.
        assert rect.edge_anchor(200, 10) == (200, 100)

    def test_overflowed_pins_have_no_anchor(self):
        pins = [
            PinSpec(id=f"n{i}", x=300 + (i % 6) * 4, y=300 + (i // 6) * 4,
                    sort_key=i, size=(150, 100))
            for i in range(30)
        ]
        results = place_cards(pins, canvas_size=(700, 700))
        for r in results:
            if not r.placed:
                assert r.anchor is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
