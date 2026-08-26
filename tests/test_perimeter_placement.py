"""Tests for the opt-in perimeter card placement (src/poster/perimeter_placement.py).

Covers the invariants the renderer relies on, plus the one crossing-reduction
property this layout actually guarantees:

  - placed cards never overlap each other (including inside the corners, where
    two cards on adjacent edges can collide even though their 1D positions on
    the border track do not)
  - cards stay inside the canvas, respecting the page margin
  - cards run around the border in the same cyclic order as their pins run
    around the canvas centre — the property that keeps neighbouring pins'
    leader lines from crossing
  - pins that genuinely do not fit overflow to the legend (placed=False)
    rather than being dropped or force-overlapped
  - a known geometry lands where a human would expect: four pins near the four
    corners of a square canvas get cards in those same four corners
"""

from __future__ import annotations

import math
from datetime import date

import pytest

from src.poster.card_placement import CardPlacement, PinSpec, Rect
from src.poster.perimeter_placement import place_cards_perimeter
from src.poster.route_index import RouteIndex

CANVAS = (2000, 2000)
MARGIN = 50


def _angle(x: float, y: float, canvas_size=CANVAS) -> float:
    """Counter-clockwise angle of a point about the canvas centre, y flipped —
    the same convention the module orders pins by."""
    cx, cy = canvas_size[0] / 2.0, canvas_size[1] / 2.0
    return math.atan2(-(y - cy), x - cx)


def _fraction(x: float, y: float, canvas_size=CANVAS, margin=MARGIN) -> float:
    """Fraction of a full turn from the track's start (the top-left corner)."""
    reference = _angle(margin, margin, canvas_size)
    return ((_angle(x, y, canvas_size) - reference) % math.tau) / math.tau


def _ring_pins(count: int, radius: float = 600, size=(200, 120),
               canvas_size=CANVAS) -> list[PinSpec]:
    """*count* pins evenly around a circle, deliberately offset so none sits
    exactly on a corner direction (where "which corner" is a coin flip)."""
    cx, cy = canvas_size[0] / 2.0, canvas_size[1] / 2.0
    pins = []
    for i in range(count):
        theta = math.tau * (i + 0.5) / count
        pins.append(PinSpec(
            id=f"p{i}",
            x=cx + radius * math.cos(theta),
            y=cy - radius * math.sin(theta),
            sort_key=i,
            size=size,
        ))
    return pins


def _placed(results: list[CardPlacement]) -> list[Rect]:
    return [r.card_rect for r in results if r.placed]


def _assert_disjoint(rects: list[Rect], gutter: float = 0.0) -> None:
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            assert not rects[i].overlaps(rects[j], gutter), (
                f"cards {i} and {j} overlap: {rects[i]} vs {rects[j]}"
            )


class TestNoOverlapAndBounds:
    def test_ring_of_pins_all_placed_without_overlap(self):
        pins = _ring_pins(10)
        results = place_cards_perimeter(pins, CANVAS, margin=MARGIN)

        assert len(results) == len(pins)
        rects = _placed(results)
        assert len(rects) == len(pins), "the border has ample room for ten cards"
        _assert_disjoint(rects)

    def test_cards_stay_inside_the_page_margin(self):
        results = place_cards_perimeter(_ring_pins(12), CANVAS, margin=MARGIN)
        for rect in _placed(results):
            assert rect.within(CANVAS, MARGIN), f"card {rect} breaks the page margin"

    def test_gutter_is_respected_between_cards(self):
        results = place_cards_perimeter(_ring_pins(12), CANVAS, margin=MARGIN, gutter=30)
        _assert_disjoint(_placed(results), gutter=30)

    def test_cards_on_adjacent_edges_do_not_collide_in_the_corners(self):
        """A card at the end of one edge and a card at the start of the next
        occupy 1D positions that do not touch, yet both sit in the corner —
        the placement has to notice that in 2D."""
        # Tall-ish cards on a small canvas: the border track is almost full, so
        # cards are pushed hard up against the corners.
        pins = _ring_pins(16, radius=300, size=(160, 150), canvas_size=(1200, 1200))
        results = place_cards_perimeter(pins, (1200, 1200), margin=20, gutter=5)
        rects = _placed(results)
        assert len(rects) >= 8, "expected most cards to fit and crowd the corners"
        _assert_disjoint(rects, gutter=5)
        for rect in rects:
            assert rect.within((1200, 1200), 20)


class TestCyclicOrderMatchesAngularOrder:
    def test_cards_run_around_the_border_in_pin_angular_order(self):
        pins = _ring_pins(12)
        results = place_cards_perimeter(pins, CANVAS, margin=MARGIN)
        assert all(r.placed for r in results)

        # Results come back in the pins' own angular order...
        by_id = {p.id: p for p in pins}
        pin_fractions = [
            _fraction(by_id[r.pin_id].x, by_id[r.pin_id].y) for r in results
        ]
        assert pin_fractions == sorted(pin_fractions)

        # ...and their cards go round the border in that same *cyclic* order.
        # The order is cyclic, not linear: where the sequence happens to start
        # is arbitrary (a card sitting across the track's own start corner
        # measures as just under a full turn, not just over zero), so the test
        # is that the sequence wraps at most once. A card that overtook its
        # neighbour would add a second wrap.
        card_fractions = [_fraction(*r.card_rect.center) for r in results]
        wraps = sum(
            1 for a, b in zip(card_fractions, card_fractions[1:]) if b < a
        )
        assert wraps <= 1, (
            f"cards are out of cyclic order around the border: {card_fractions}"
        )

    def test_order_is_independent_of_input_order(self):
        pins = _ring_pins(9)
        forward = place_cards_perimeter(pins, CANVAS, margin=MARGIN)
        reversed_ = place_cards_perimeter(list(reversed(pins)), CANVAS, margin=MARGIN)
        assert forward == reversed_


class TestKnownGeometry:
    def test_four_corner_pins_get_cards_in_their_own_corners(self):
        """A square canvas maps corner directions exactly onto track corners,
        so each of these four pins should end up with a card in the corner it
        sits nearest."""
        corners = {
            "top_left": (300, 300),
            "bottom_left": (300, 1700),
            "bottom_right": (1700, 1700),
            "top_right": (1700, 300),
        }
        pins = [
            PinSpec(id=name, x=x, y=y, sort_key=name, size=(200, 120))
            for name, (x, y) in corners.items()
        ]
        results = {r.pin_id: r for r in
                   place_cards_perimeter(pins, CANVAS, margin=MARGIN)}
        assert all(r.placed for r in results.values())

        # Each card must be nearer its own pin's corner of the page than any
        # other corner of the page.
        page_corners = {
            "top_left": (MARGIN, MARGIN),
            "bottom_left": (MARGIN, CANVAS[1] - MARGIN),
            "bottom_right": (CANVAS[0] - MARGIN, CANVAS[1] - MARGIN),
            "top_right": (CANVAS[0] - MARGIN, MARGIN),
        }
        for name, result in results.items():
            cx, cy = result.card_rect.center
            nearest = min(
                page_corners,
                key=lambda k: math.hypot(cx - page_corners[k][0], cy - page_corners[k][1]),
            )
            assert nearest == name, (
                f"pin at {corners[name]} got a card near the {nearest} corner"
            )

    def test_anchor_lies_on_the_card_border(self):
        pins = _ring_pins(6)
        for result in place_cards_perimeter(pins, CANVAS, margin=MARGIN):
            rect, (ax, ay) = result.card_rect, result.anchor
            on_vertical = ax in (rect.left, rect.right) and rect.top <= ay <= rect.bottom
            on_horizontal = ay in (rect.top, rect.bottom) and rect.left <= ax <= rect.right
            assert on_vertical or on_horizontal


class TestOverflow:
    def test_pins_that_cannot_fit_the_border_go_to_the_legend(self):
        # 40 cards of 200px extent need ~8000px of border; this track offers
        # 2 * (900 + 900) = 3600px, so most of them cannot fit.
        pins = _ring_pins(40, radius=300, size=(200, 200), canvas_size=(1000, 1000))
        results = place_cards_perimeter(pins, (1000, 1000), margin=50)

        assert len(results) == 40, "every pin must appear in the output"
        assert {r.pin_id for r in results} == {p.id for p in pins}

        overflowed = [r for r in results if not r.placed]
        assert overflowed, "the border is far too short for all these cards"
        for r in overflowed:
            assert r.card_rect is None
            assert r.anchor is None

        rects = _placed(results)
        _assert_disjoint(rects)
        for rect in rects:
            assert rect.within((1000, 1000), 50)

    def test_a_card_deeper_than_the_page_never_gets_placed(self):
        """A card taller than the canvas can sit on no edge at all — it must
        overflow rather than be placed out of bounds."""
        pin = PinSpec(id="huge", x=1000, y=200, sort_key=1, size=(200, 5000))
        result = place_cards_perimeter([pin], CANVAS, margin=MARGIN)[0]
        assert not result.placed
        assert result.card_rect is None


class TestEdgeCases:
    def test_no_pins_returns_empty_list(self):
        assert place_cards_perimeter([], CANVAS, margin=MARGIN) == []

    def test_single_pin_gets_a_card_on_the_border(self):
        pin = PinSpec(id="only", x=1000, y=400, sort_key=1, size=(200, 120))
        result = place_cards_perimeter([pin], CANVAS, margin=MARGIN)[0]
        assert result.placed
        rect = result.card_rect
        assert rect.within(CANVAS, MARGIN)
        # It hugs one of the four page edges rather than floating in the map.
        assert (rect.left == MARGIN or rect.top == MARGIN
                or rect.right == CANVAS[0] - MARGIN
                or rect.bottom == CANVAS[1] - MARGIN)

    def test_a_route_does_not_change_the_placement(self):
        """Unlike the radial search, this layout is border-bound: the route
        index is only reported on, never used to pick a position."""
        pins = _ring_pins(8)
        route = RouteIndex([[(x, 1000) for x in range(0, 2000, 10)]], CANVAS)
        assert (place_cards_perimeter(pins, CANVAS, margin=MARGIN, route=route)
                == place_cards_perimeter(pins, CANVAS, margin=MARGIN))

    def test_pin_at_the_canvas_centre_is_still_placed(self):
        """atan2(0, 0) is 0 rather than undefined; a pin sitting exactly on the
        centre must not blow up or be silently dropped."""
        pin = PinSpec(id="c", x=1000, y=1000, sort_key=1, size=(200, 120))
        result = place_cards_perimeter([pin], CANVAS, margin=MARGIN)[0]
        assert result.placed


# ---------------------------------------------------------------------------
# Title/trip-summary obstacle avoidance (title-config feature): the resolved
# title rect is passed in as an extra `obstacles` entry, treated exactly like
# an already-placed card — checked with a plain 2D overlap, not limited to
# rectangles that themselves sit on the border track.
# ---------------------------------------------------------------------------

class TestObstacleAvoidance:
    def test_card_does_not_overlap_an_obstacle_covering_its_natural_spot(self):
        pin = PinSpec(id="only", x=1000, y=400, sort_key=1, size=(200, 120))
        naive = place_cards_perimeter([pin], CANVAS, margin=MARGIN)[0].card_rect

        result = place_cards_perimeter(
            [pin], CANVAS, margin=MARGIN, obstacles=[naive])[0]
        assert result.placed
        assert not result.card_rect.overlaps(naive)

    def test_placed_cards_still_avoid_each_other_alongside_an_obstacle(self):
        pins = _ring_pins(6, radius=300, size=(150, 90))
        # The top-left corner, where the border track (and several of this
        # ring's natural positions) start.
        obstacle = Rect(MARGIN, MARGIN, MARGIN + 220, MARGIN + 160)
        results = place_cards_perimeter(
            pins, CANVAS, margin=MARGIN, obstacles=[obstacle])

        rects = _placed(results)
        assert rects, "expected at least one card to still be placeable"
        _assert_disjoint(rects)
        for rect in rects:
            assert not rect.overlaps(obstacle)

    def test_obstacles_never_appear_as_a_result(self):
        pins = _ring_pins(4)
        results = place_cards_perimeter(
            pins, CANVAS, margin=MARGIN, obstacles=[Rect(0, 0, 100, 100)])
        assert {r.pin_id for r in results} == {p.id for p in pins}

    def test_no_obstacles_behaves_exactly_like_before(self):
        pins = _ring_pins(10)
        with_empty = place_cards_perimeter(pins, CANVAS, margin=MARGIN, obstacles=[])
        without_kwarg = place_cards_perimeter(pins, CANVAS, margin=MARGIN)
        assert with_empty == without_kwarg


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
