"""Deterministic, non-overlapping placement of memory cards on a trip poster.

Part of issue #14 (A0 poster generation). This module is pure algorithmic
Python: no DB, no image library, no FastAPI.

Two things changed after the first round of feedback:

  - **Cards are no longer all the same size.** Each pin carries its own card
    dimensions (see ``src/poster/card_layout.py``, which measures a card from
    its actual content), so placement works with per-pin rectangles.

  - **Placement avoids the track.** Cards used to be positioned with no
    knowledge of the route, so they routinely landed on top of it and the
    poster ended up criss-crossed with leader lines cutting over the very
    track the poster is about. Candidates are now *scored* rather than
    first-fit accepted, and covering the route (or crossing it with a leader
    line) is heavily penalised.

Algorithm
---------
1. Sort pins by ``sort_key`` (ascending) so placement is deterministic and
   matches chronological order. Ties keep the input's relative order.
2. For each pin, generate candidate rectangles: 16 directions at increasing
   radius, from a minimum leader length up to a maximum search radius.
3. Reject candidates that leave the canvas or overlap an already-placed card,
   then *score* the rest — shorter leader lines are better, sitting on the
   route is much worse, and a leader crossing the route or another card is
   worse still. The lowest-scoring candidate wins.
4. If every candidate is rejected outright, the pin overflows: it is reported
   with ``placed=False`` and belongs in a numbered legend instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence, Tuple

from src.poster.route_index import RouteIndex


@dataclass(frozen=True)
class PinSpec:
    """One memory pin, and the size of the card that belongs to it.

    ``id`` must be a stable identifier (used only to tag the result, never
    interpreted). ``x``/``y`` are the pin's already-projected pixel position on
    the poster canvas. ``size`` is that card's measured ``(width, height)``.
    ``sort_key`` is any orderable value (typically the memory's date) that
    determines processing order and therefore which pins "win" contested space.
    """

    id: Any
    x: float
    y: float
    sort_key: Any
    size: Tuple[int, int]


@dataclass(frozen=True)
class Rect:
    """An axis-aligned pixel rectangle, defined by its edges."""

    left: float
    top: float
    right: float
    bottom: float

    @property
    def center(self) -> Tuple[float, float]:
        return (self.left + self.right) / 2, (self.top + self.bottom) / 2

    def overlaps(self, other: "Rect", margin: float = 0.0) -> bool:
        """True if this rectangle and ``other`` share interior area.

        ``margin`` inflates this rectangle first, so cards can be required to
        keep a visible gutter rather than merely not overlapping.
        """
        return not (
            self.right + margin <= other.left
            or self.left - margin >= other.right
            or self.bottom + margin <= other.top
            or self.top - margin >= other.bottom
        )

    def within(self, canvas_size: Tuple[float, float], margin: float = 0.0) -> bool:
        """True if this rectangle is fully inside a 0,0-origin canvas."""
        canvas_w, canvas_h = canvas_size
        return (
            self.left >= margin
            and self.top >= margin
            and self.right <= canvas_w - margin
            and self.bottom <= canvas_h - margin
        )

    def contains_point(self, x: float, y: float) -> bool:
        return self.left <= x <= self.right and self.top <= y <= self.bottom

    def edge_anchor(self, x: float, y: float) -> Tuple[float, float]:
        """The point on this rectangle's border nearest to (x, y).

        Leader lines are drawn to this point rather than to the card's centre:
        a line into the centre visibly runs *underneath* the card, and every
        card ends up with a line stabbing through it.
        """
        cx = min(max(x, self.left), self.right)
        cy = min(max(y, self.top), self.bottom)
        # Snap to whichever border is closest, so the anchor sits on the
        # outline rather than inside the card when the pin is alongside it.
        distances = (
            (abs(cx - self.left), (self.left, cy)),
            (abs(cx - self.right), (self.right, cy)),
            (abs(cy - self.top), (cx, self.top)),
            (abs(cy - self.bottom), (cx, self.bottom)),
        )
        return min(distances, key=lambda d: d[0])[1]


@dataclass(frozen=True)
class CardPlacement:
    """Result of trying to place a card for one pin.

    ``placed=True`` means ``card_rect`` is a non-overlapping, in-bounds
    rectangle the caller should render a card into, connected to the pin by a
    leader line ending at ``anchor`` (a point on the card's border).

    ``placed=False`` means no such rectangle could be found. ``card_rect`` is
    then ``None``: the caller must NOT render a card. It should still draw the
    pin marker and add the pin to a numbered overflow legend.
    """

    pin_id: Any
    placed: bool
    card_rect: Optional[Rect]
    anchor: Optional[Tuple[float, float]] = None


# 16 directions rather than 8: with variable-size cards, twice the angular
# resolution meaningfully improves the chance of finding a clean spot near the
# pin before the search has to push the card further away.
_NUM_DIRECTIONS = 16
_DIRECTIONS: Tuple[Tuple[float, float], ...] = tuple(
    (
        math.cos(math.radians(-90 + 360 * i / _NUM_DIRECTIONS)),
        math.sin(math.radians(-90 + 360 * i / _NUM_DIRECTIONS)),
    )
    for i in range(_NUM_DIRECTIONS)
)

# Scoring weights, in units of "pixels of leader line" so they can be compared
# directly against the distance term.
_ROUTE_OVERLAP_PENALTY = 100_000.0
_LEADER_CROSSES_ROUTE_PENALTY = 25_000.0
_LEADER_CROSSES_CARD_PENALTY = 50_000.0
_PIN_COVERED_PENALTY = 40_000.0


def _candidate_rect(
    pin_x: float, pin_y: float, dx: float, dy: float, radius: float,
    card_size: Tuple[int, int],
) -> Rect:
    """Card rectangle centred at (pin + radius * direction)."""
    card_w, card_h = card_size
    cx = pin_x + dx * radius
    cy = pin_y + dy * radius
    left = round(cx - card_w / 2)
    top = round(cy - card_h / 2)
    return Rect(left=left, top=top, right=left + card_w, bottom=top + card_h)


def place_cards(
    pins: Sequence[PinSpec],
    canvas_size: Tuple[int, int],
    *,
    route: Optional[RouteIndex] = None,
    other_pins: bool = True,
    margin: float = 0.0,
    gutter: float = 0.0,
    min_radius: Optional[float] = None,
    max_radius: Optional[float] = None,
    radius_step: Optional[float] = None,
) -> List[CardPlacement]:
    """Place each pin's card without overlaps, avoiding the route where possible.

    Pins are processed in ascending ``sort_key`` order (stable for ties), so
    earlier memories claim contested space first and results are deterministic
    across runs for the same input.

    Args:
        pins: Pins to place cards for; each carries its own card ``size``.
        canvas_size: ``(width, height)`` of the poster in pixels.
        route: Index of the projected track. Candidates covering the route are
            heavily penalised, so cards settle beside the track rather than on
            top of it. ``None`` disables route awareness entirely.
        other_pins: Penalise candidates that bury another memory's pin.
        margin: Keep cards this far inside the canvas edge.
        gutter: Minimum gap to maintain between two cards.
        min_radius: Shortest leader length to try. Defaults to 0.62x the card's
            longer side — far enough to clear the pin, short enough to keep the
            leader line unobtrusive.
        max_radius: Longest leader length to try. Defaults to 6x ``min_radius``.
        radius_step: Distance between successive radii. Defaults to a twelfth
            of the (max - min) span.

    Returns:
        One ``CardPlacement`` per input pin, in processing (sorted) order.
    """
    sorted_pins = sorted(pins, key=lambda p: p.sort_key)
    pin_points = [(p.x, p.y) for p in sorted_pins]

    placed_rects: List[Rect] = []
    results: List[CardPlacement] = []

    for pin in sorted_pins:
        card_w, card_h = pin.size
        longest = max(card_w, card_h)
        lo = 0.62 * longest if min_radius is None else min_radius
        hi = 6 * lo if max_radius is None else max_radius
        step = max(1.0, (hi - lo) / 12) if radius_step is None else radius_step

        best: Optional[Rect] = None
        best_score = math.inf

        radius = lo
        while radius <= hi:
            for dx, dy in _DIRECTIONS:
                candidate = _candidate_rect(pin.x, pin.y, dx, dy, radius, pin.size)
                if not candidate.within(canvas_size, margin):
                    continue
                if any(candidate.overlaps(existing, gutter) for existing in placed_rects):
                    continue

                score = _score(
                    candidate, pin, radius, route, placed_rects,
                    pin_points if other_pins else (),
                )
                if score < best_score:
                    best_score = score
                    best = candidate
            # A clean, close placement can't be beaten by anything further out,
            # so stop widening the search as soon as one is found.
            if best is not None and best_score < _LEADER_CROSSES_ROUTE_PENALTY:
                break
            radius += step

        if best is not None:
            placed_rects.append(best)
            results.append(CardPlacement(
                pin_id=pin.id, placed=True, card_rect=best,
                anchor=best.edge_anchor(pin.x, pin.y),
            ))
        else:
            results.append(CardPlacement(pin_id=pin.id, placed=False, card_rect=None))

    return results


def _score(
    candidate: Rect,
    pin: PinSpec,
    radius: float,
    route: Optional[RouteIndex],
    placed_rects: Sequence[Rect],
    pin_points: Sequence[Tuple[float, float]],
) -> float:
    """Lower is better. Distance from the pin, plus penalties for the things
    that made earlier posters unreadable."""
    score = radius

    anchor = candidate.edge_anchor(pin.x, pin.y)

    if route is not None and route:
        if route.intersects_rect(candidate.left, candidate.top,
                                 candidate.right, candidate.bottom):
            score += _ROUTE_OVERLAP_PENALTY
        if route.crosses_segment(pin.x, pin.y, anchor[0], anchor[1]):
            score += _LEADER_CROSSES_ROUTE_PENALTY

    for other in placed_rects:
        if _segment_hits_rect(pin.x, pin.y, anchor[0], anchor[1], other):
            score += _LEADER_CROSSES_CARD_PENALTY
            break

    for px, py in pin_points:
        if (px, py) != (pin.x, pin.y) and candidate.contains_point(px, py):
            score += _PIN_COVERED_PENALTY
            break

    return score


def _segment_hits_rect(x1: float, y1: float, x2: float, y2: float, rect: Rect) -> bool:
    from src.poster.route_index import _segment_intersects_rect

    return _segment_intersects_rect(
        (x1, y1, x2, y2), rect.left, rect.top, rect.right, rect.bottom
    )
