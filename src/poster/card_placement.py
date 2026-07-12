"""Deterministic, non-overlapping placement of memory cards on a trip poster.

Part of issue #14 (A0 poster generation). This module is pure algorithmic
Python: no DB, no image library, no FastAPI. It solves a simplified version
of label placement: every card has the *same* fixed size (one global poster
content config), so instead of general rectangle packing we only need to pick
one of a handful of candidate positions around each pin.

Algorithm
---------
1. Sort pins by ``sort_key`` (ascending) so placement is deterministic and
   matches chronological order. Ties keep the input's relative order
   (Python's sort is stable).
2. Process pins one at a time. For each pin, walk outward through a ring of
   candidate positions: 8 compass directions (N, NE, E, SE, S, SW, W, NW)
   evaluated at increasing radius, from a minimum leader-line length up to a
   maximum search radius.
3. Accept the first candidate rectangle that (a) fits fully inside the
   canvas and (b) does not overlap any card already placed for an earlier
   pin.
4. If no candidate at any radius/direction works, the pin is reported as an
   "overflow" (``placed=False``, ``card_rect=None``) instead of forcing an
   overlapping placement. The caller is expected to still draw the pin
   itself and list overflowed pins in a small numbered legend.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PinSpec:
    """One memory pin to place a card for.

    ``id`` must be a stable identifier (used only to tag the result, never
    interpreted). ``x``/``y`` are the pin's already-projected pixel position
    on the poster canvas. ``sort_key`` is any orderable value (typically the
    memory's date) that determines processing order and therefore which
    pins "win" contested space when cards would otherwise overlap.
    """

    id: Any
    x: float
    y: float
    sort_key: Any


@dataclass(frozen=True)
class Rect:
    """An axis-aligned pixel rectangle, defined by its edges."""

    left: float
    top: float
    right: float
    bottom: float

    def overlaps(self, other: "Rect") -> bool:
        """True if this rectangle and ``other`` share any interior area.

        Rectangles that merely touch at an edge (e.g. this.right ==
        other.left) do not count as overlapping.
        """
        return not (
            self.right <= other.left
            or self.left >= other.right
            or self.bottom <= other.top
            or self.top >= other.bottom
        )

    def within(self, canvas_size: tuple[float, float]) -> bool:
        """True if this rectangle is fully inside a 0,0-origin canvas."""
        canvas_w, canvas_h = canvas_size
        return (
            self.left >= 0
            and self.top >= 0
            and self.right <= canvas_w
            and self.bottom <= canvas_h
        )


@dataclass(frozen=True)
class CardPlacement:
    """Result of trying to place a card for one pin.

    ``placed=True`` means ``card_rect`` is a non-overlapping, in-bounds
    rectangle the caller should render a card into, connected to the pin by
    a leader line.

    ``placed=False`` means no such rectangle could be found within the
    search radius (the pin sits in too dense a cluster). ``card_rect`` is
    then ``None``: the caller must NOT render a card for this pin. Instead
    it should still draw the pin marker on the map and add this pin to a
    small numbered overflow legend elsewhere on the poster.
    """

    pin_id: Any
    placed: bool
    card_rect: Optional[Rect]


# 8 compass directions (N, NE, E, SE, S, SW, W, NW) as unit vectors, in a
# fixed, deterministic order. Angles start at -90 degrees (up, i.e. north,
# since pixel y grows downward) and step clockwise in 45 degree increments.
_NUM_DIRECTIONS = 8
_DIRECTIONS: tuple[tuple[float, float], ...] = tuple(
    (
        math.cos(math.radians(-90 + 360 * i / _NUM_DIRECTIONS)),
        math.sin(math.radians(-90 + 360 * i / _NUM_DIRECTIONS)),
    )
    for i in range(_NUM_DIRECTIONS)
)


def _candidate_rect(
    pin_x: float, pin_y: float, dx: float, dy: float, radius: float, card_size: tuple[int, int]
) -> Rect:
    """Card rectangle centred at (pin + radius * direction)."""
    card_w, card_h = card_size
    cx = pin_x + dx * radius
    cy = pin_y + dy * radius
    return Rect(
        left=round(cx - card_w / 2),
        top=round(cy - card_h / 2),
        right=round(cx - card_w / 2) + card_w,
        bottom=round(cy - card_h / 2) + card_h,
    )


def place_cards(
    pins: list[PinSpec],
    card_size: tuple[int, int],
    canvas_size: tuple[int, int],
    *,
    min_radius: Optional[float] = None,
    max_radius: Optional[float] = None,
    radius_step: Optional[float] = None,
) -> list[CardPlacement]:
    """Place a fixed-size card near each pin without any card overlapping.

    Pins are processed in ascending ``sort_key`` order (stable for ties), so
    earlier memories claim contested space first and results are
    deterministic across runs given the same input.

    For each pin, candidate card positions are tried at increasing radius
    (``min_radius`` up to ``max_radius``, stepping by ``radius_step``), and
    at each radius the 8 compass directions are tried in a fixed order
    (N, NE, E, SE, S, SW, W, NW). The first candidate that lands fully
    within ``canvas_size`` and does not overlap any already-placed card is
    used. If every candidate is rejected, the pin is reported with
    ``placed=False`` and ``card_rect=None`` — see ``CardPlacement`` for the
    contract this implies for the caller (draw pin + legend entry, no
    card).

    If not given explicitly, ``min_radius``/``max_radius``/``radius_step``
    are derived from ``card_size`` so the search scales with card size
    (and therefore poster resolution) instead of being tuned to one fixed
    pixel scale:
      - ``min_radius`` defaults to 0.75x the card's longer side, enough
        that the card clears the pin marker itself, leaving a short but
        visible leader line.
      - ``max_radius`` defaults to 6x ``min_radius``.
      - ``radius_step`` defaults to an eighth of the (max - min) span.

    Args:
        pins: Pins to place cards for.
        card_size: ``(width, height)`` in pixels, identical for every card.
        canvas_size: ``(width, height)`` of the poster in pixels; card rects
            must stay fully within ``[0, width] x [0, height]``.
        min_radius: Shortest leader-line length to try, in pixels.
        max_radius: Longest leader-line length to try, in pixels.
        radius_step: Distance between successive tried radii, in pixels.

    Returns:
        One ``CardPlacement`` per input pin, in the same (sorted) order they
        were processed in.
    """
    card_w, card_h = card_size

    if min_radius is None:
        min_radius = 0.75 * max(card_w, card_h)
    if max_radius is None:
        max_radius = 6 * min_radius
    if radius_step is None:
        radius_step = max(1.0, (max_radius - min_radius) / 8)

    sorted_pins = sorted(pins, key=lambda p: p.sort_key)

    placed_rects: list[Rect] = []
    results: list[CardPlacement] = []

    for pin in sorted_pins:
        chosen: Optional[Rect] = None

        radius = min_radius
        while radius <= max_radius and chosen is None:
            for dx, dy in _DIRECTIONS:
                candidate = _candidate_rect(pin.x, pin.y, dx, dy, radius, card_size)
                if not candidate.within(canvas_size):
                    continue
                if any(candidate.overlaps(existing) for existing in placed_rects):
                    continue
                chosen = candidate
                break
            radius += radius_step

        if chosen is not None:
            placed_rects.append(chosen)
            results.append(CardPlacement(pin_id=pin.id, placed=True, card_rect=chosen))
        else:
            results.append(CardPlacement(pin_id=pin.id, placed=False, card_rect=None))

    return results
