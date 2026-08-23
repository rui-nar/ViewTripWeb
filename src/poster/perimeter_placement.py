"""Opt-in prototype: lay every memory card along the poster's border.

``card_placement.place_cards`` searches outwards from each pin in 16
directions until it finds a clean spot. This module is a *different* algorithm,
not a variation of it: cards are laid out in one dimension along the page
border, and the map area in the middle is left entirely to the track. It is
selected with the request's ``config.layout == "perimeter"`` and is otherwise
never used — the radial search stays the default.

Algorithm
---------
1. Order pins by their angle around the canvas centre. That angle is measured
   with the y axis flipped, so a growing angle reads counter-clockwise on the
   printed sheet.
2. Unroll the page-margin rectangle into a 1D track, counter-clockwise from its
   top-left corner: down the left edge, right along the bottom, up the right
   edge, left along the top. Each pin's angle maps proportionally onto that
   track, giving the card its "natural" position.
3. Walk the pins in angular order and compact greedily: each card starts at the
   later of its natural position and the previous card's end (plus a gutter).
   Because that walk only ever moves forward, cards end up in the *same cyclic
   order around the border as their pins are around the centre* — which is what
   stops neighbouring pins' leader lines crossing each other. It is only a
   local guarantee: an interior pin can still get a long leader, and leaders
   from opposite sides of the map can still cross. Full leader-line crossing
   avoidance is deliberately out of scope for this prototype.
4. Pins whose card cannot fit anywhere left on the track overflow, exactly as
   in the radial placement: ``placed=False``, and the caller lists them in the
   numbered legend.

The one thing corners force on the algorithm: a card is a single axis-aligned
rectangle, so it cannot bend around a corner. A card whose extent would
straddle two edges is pushed onto the next edge instead. Cards on two adjacent
edges can also collide *inside* the corner even when their 1D intervals do not
touch (a card at the end of the left edge and one at the start of the bottom
edge both occupy the bottom-left corner), so each candidate is additionally
checked in 2D and pushed past whatever it hits.
"""

from __future__ import annotations

import logging
import math
from typing import List, Optional, Sequence, Tuple

from src.poster.card_placement import CardPlacement, PinSpec, Rect
from src.poster.route_index import RouteIndex

_log = logging.getLogger(__name__)


class _Track:
    """The border rectangle, unrolled into a 1D arc-length coordinate.

    Segments run counter-clockwise (as seen on the sheet, with y growing
    downwards) from the top-left corner: ``LEFT`` runs down, ``BOTTOM`` runs
    right, ``RIGHT`` runs up, ``TOP`` runs left.
    """

    LEFT, BOTTOM, RIGHT, TOP = range(4)

    def __init__(self, canvas_size: Tuple[int, int], margin: float):
        canvas_w, canvas_h = canvas_size
        self.left = float(margin)
        self.top = float(margin)
        self.right = canvas_w - margin
        self.bottom = canvas_h - margin
        span_x = self.right - self.left
        span_y = self.bottom - self.top
        self.lengths = (span_y, span_x, span_y, span_x)
        self.length = 2 * (span_x + span_y)
        self.center = (canvas_w / 2.0, canvas_h / 2.0)

    def segment(self, position: float) -> Tuple[int, float]:
        """``(segment index, offset within that segment)`` for *position*.

        Positions are cyclic: the caller keeps walking forward past the end of
        the track and wraps back round to the top-left corner.
        """
        offset = position % self.length
        for index, length in enumerate(self.lengths):
            if offset < length:
                return index, offset
            offset -= length
        return self.TOP, self.lengths[self.TOP]

    def segment_end(self, position: float) -> float:
        """Arc length at the end of the segment *position* falls in."""
        index, offset = self.segment(position)
        return position + (self.lengths[index] - offset)

    def rect_at(self, position: float, card_size: Tuple[int, int]
                ) -> Optional[Tuple[Rect, float]]:
        """``(card rectangle, its end position)`` for a card starting at *position*.

        ``None`` when the card would straddle a corner: a card is one
        axis-aligned rectangle and cannot bend, so the caller must push it onto
        the next edge instead.
        """
        card_w, card_h = card_size
        index, offset = self.segment(position)
        extent = card_h if index in (self.LEFT, self.RIGHT) else card_w
        if offset + extent > self.lengths[index]:
            return None

        if index == self.LEFT:
            top = self.top + offset
            rect = Rect(self.left, top, self.left + card_w, top + card_h)
        elif index == self.BOTTOM:
            left = self.left + offset
            rect = Rect(left, self.bottom - card_h, left + card_w, self.bottom)
        elif index == self.RIGHT:
            bottom = self.bottom - offset
            rect = Rect(self.right - card_w, bottom - card_h, self.right, bottom)
        else:
            right = self.right - offset
            rect = Rect(right - card_w, self.top, right, self.top + card_h)
        return rect, position + extent

    def advance_past(self, position: float, blocker: Rect, gutter: float) -> float:
        """The position, further along the track, at which a card clears *blocker*.

        Separation is only computed along the direction this edge travels in,
        which is the direction the search moves. That is enough for the two
        cases the compaction actually produces — the previous card on the same
        edge, and a card on the adjoining edge sharing the corner.
        """
        index, offset = self.segment(position)
        segment_start = position - offset
        if index == self.LEFT:
            needed = blocker.bottom + gutter - self.top
        elif index == self.BOTTOM:
            needed = blocker.right + gutter - self.left
        elif index == self.RIGHT:
            needed = self.bottom + gutter - blocker.top
        else:
            needed = self.right + gutter - blocker.left
        return segment_start + needed


def _find_slot(
    track: _Track,
    start: float,
    card_size: Tuple[int, int],
    placed: Sequence[Rect],
    canvas_size: Tuple[int, int],
    margin: float,
    gutter: float,
) -> Optional[Tuple[Rect, float]]:
    """First slot at or after *start* that holds this card cleanly, or None.

    The search wraps round the corner the track started at, so a pin whose
    natural position lands just short of the end still gets the space before
    the first card. It gives up after one full lap: by then every remaining
    position is blocked by a card already placed.
    """
    limit = start + track.length
    position = start
    while position < limit:
        slot = track.rect_at(position, card_size)
        if slot is None or not slot[0].within(canvas_size, margin):
            # Straddles a corner, or is too deep for this edge to hold at all:
            # neither gets better further along the same edge.
            position = track.segment_end(position)
            continue
        rect = slot[0]
        blocker = next((other for other in placed if rect.overlaps(other, gutter)), None)
        if blocker is None:
            return slot
        nudged = track.advance_past(position, blocker, gutter)
        # Two cards can be a floating-point whisker apart yet still count as
        # overlapping, in which case "just past this blocker" lands back on the
        # position we are already at. Step to the next edge instead of spinning.
        position = nudged if nudged > position else track.segment_end(position)
    return None


def place_cards_perimeter(
    pins: Sequence[PinSpec],
    canvas_size: Tuple[int, int],
    *,
    route: Optional[RouteIndex] = None,
    margin: float = 0.0,
    gutter: float = 0.0,
) -> List[CardPlacement]:
    """Place each pin's card along the page border, clear of the map area.

    Same contract as ``card_placement.place_cards``: one ``CardPlacement`` per
    input pin, never overlapping, never outside the canvas, with unplaceable
    pins reported as ``placed=False`` for the legend. Results come back in the
    order the cards run around the border (angular order around the canvas
    centre), which is this algorithm's processing order — not ``sort_key``
    order, which is what the radial placement uses.

    Args:
        pins: Pins to place cards for; each carries its own card ``size``.
        canvas_size: ``(width, height)`` of the poster in pixels.
        route: Index of the projected track. Cards sit on the border by
            construction, so unlike the radial search this is not used to
            choose between positions; it only reports how many leader lines
            end up crossing the track.
        margin: Keep cards this far inside the canvas edge. The border track
            runs along this inset rectangle.
        gutter: Minimum gap to maintain between two cards.
    """
    track = _Track(canvas_size, margin)
    center_x, center_y = track.center

    def angle(x: float, y: float) -> float:
        # y is flipped so that a growing angle reads counter-clockwise on the
        # printed sheet, matching the direction the track itself runs in.
        return math.atan2(-(y - center_y), x - center_x)

    # The track starts at the top-left corner, so pin angles are measured from
    # that same corner's direction: a pin's fraction of a full turn is directly
    # its fraction of the way along the track.
    reference = angle(track.left, track.top)

    def track_fraction(pin: PinSpec) -> float:
        return ((angle(pin.x, pin.y) - reference) % math.tau) / math.tau

    ordered = sorted(pins, key=track_fraction)

    placed_rects: List[Rect] = []
    results: List[CardPlacement] = []
    cursor = 0.0

    for pin in ordered:
        natural = track_fraction(pin) * track.length
        slot = _find_slot(
            track, max(natural, cursor), pin.size, placed_rects,
            canvas_size, margin, gutter,
        )
        if slot is None:
            results.append(CardPlacement(pin_id=pin.id, placed=False, card_rect=None))
            continue
        rect, end = slot
        placed_rects.append(rect)
        cursor = end + gutter
        results.append(CardPlacement(
            pin_id=pin.id, placed=True, card_rect=rect,
            anchor=rect.edge_anchor(pin.x, pin.y),
        ))

    if route is not None and route:
        by_id = {pin.id: pin for pin in ordered}
        crossings = sum(
            1 for r in results
            if r.placed and route.crosses_segment(
                by_id[r.pin_id].x, by_id[r.pin_id].y, r.anchor[0], r.anchor[1])
        )
        _log.debug(
            "Perimeter placement: %d/%d cards placed, %d leader line(s) cross the route",
            len(placed_rects), len(results), crossings,
        )

    return results
