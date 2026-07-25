"""Spatial index for testing whether a rectangle covers the trip's track.

Poster cards that land on top of the route are the single most visible layout
failure: the track is the subject of the poster, and a card sitting across it
hides the very thing the reader is following. Card placement therefore needs a
cheap "does this rectangle touch the route?" query.

A full A0 render projects hundreds of thousands of track points, and placement
evaluates dozens of candidate rectangles per pin, so a linear scan over every
segment per query is far too slow. This module buckets segments into a uniform
grid once, then answers each query against only the segments in the cells the
rectangle actually covers.

Pure geometry: no Pillow, no DB, no projection. Fully unit-testable.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Set, Tuple

Point = Tuple[float, float]
Segment = Tuple[float, float, float, float]  # x1, y1, x2, y2


def _segments_from_polylines(polylines: Iterable[Sequence[Point]]) -> List[Segment]:
    segments: List[Segment] = []
    for line in polylines:
        previous: Point | None = None
        for point in line:
            if previous is not None:
                # Skip zero-length segments; they carry no geometry and would
                # only bloat the index.
                if point != previous:
                    segments.append((previous[0], previous[1], point[0], point[1]))
            previous = point
    return segments


class RouteIndex:
    """Uniform-grid index over the projected route's line segments."""

    def __init__(
        self,
        polylines: Iterable[Sequence[Point]],
        canvas_size: Tuple[int, int],
        cell_size: float | None = None,
    ):
        self.segments = _segments_from_polylines(polylines)
        canvas_w, canvas_h = canvas_size
        # A cell around a card's own size keeps the number of cells a query
        # touches small while keeping per-cell segment lists short.
        self.cell = float(cell_size or max(32.0, max(canvas_w, canvas_h) / 64.0))
        self._grid: Dict[Tuple[int, int], List[int]] = {}
        for index, seg in enumerate(self.segments):
            for key in self._cells_for_bbox(min(seg[0], seg[2]), min(seg[1], seg[3]),
                                            max(seg[0], seg[2]), max(seg[1], seg[3])):
                self._grid.setdefault(key, []).append(index)

    def __bool__(self) -> bool:
        return bool(self.segments)

    def _cells_for_bbox(self, left: float, top: float, right: float, bottom: float):
        cx0 = int(left // self.cell)
        cx1 = int(right // self.cell)
        cy0 = int(top // self.cell)
        cy1 = int(bottom // self.cell)
        for cy in range(cy0, cy1 + 1):
            for cx in range(cx0, cx1 + 1):
                yield (cx, cy)

    def _candidate_indices(self, left: float, top: float, right: float, bottom: float) -> Set[int]:
        found: Set[int] = set()
        for key in self._cells_for_bbox(left, top, right, bottom):
            bucket = self._grid.get(key)
            if bucket:
                found.update(bucket)
        return found

    def intersects_rect(self, left: float, top: float, right: float, bottom: float) -> bool:
        """True if any route segment enters the given rectangle."""
        for index in self._candidate_indices(left, top, right, bottom):
            if _segment_intersects_rect(self.segments[index], left, top, right, bottom):
                return True
        return False

    def crosses_segment(self, x1: float, y1: float, x2: float, y2: float) -> bool:
        """True if the given line segment crosses the route.

        Used for leader lines, which should reach their card without cutting
        across the track any more than the card itself does.
        """
        left, right = (x1, x2) if x1 <= x2 else (x2, x1)
        top, bottom = (y1, y2) if y1 <= y2 else (y2, y1)
        for index in self._candidate_indices(left, top, right, bottom):
            if _segments_cross(self.segments[index], (x1, y1, x2, y2)):
                return True
        return False


# ── Primitive geometry ────────────────────────────────────────────────────────

def _orientation(ax, ay, bx, by, cx, cy) -> float:
    return (by - ay) * (cx - bx) - (bx - ax) * (cy - by)


def _on_segment(ax, ay, bx, by, px, py) -> bool:
    return min(ax, bx) <= px <= max(ax, bx) and min(ay, by) <= py <= max(ay, by)


def _segments_cross(s1: Segment, s2: Segment) -> bool:
    """Standard orientation-test segment intersection, including collinear touching."""
    ax, ay, bx, by = s1
    cx, cy, dx, dy = s2
    d1 = _orientation(ax, ay, bx, by, cx, cy)
    d2 = _orientation(ax, ay, bx, by, dx, dy)
    d3 = _orientation(cx, cy, dx, dy, ax, ay)
    d4 = _orientation(cx, cy, dx, dy, bx, by)

    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    if d1 == 0 and _on_segment(ax, ay, bx, by, cx, cy):
        return True
    if d2 == 0 and _on_segment(ax, ay, bx, by, dx, dy):
        return True
    if d3 == 0 and _on_segment(cx, cy, dx, dy, ax, ay):
        return True
    if d4 == 0 and _on_segment(cx, cy, dx, dy, bx, by):
        return True
    return False


def _segment_intersects_rect(seg: Segment, left: float, top: float,
                             right: float, bottom: float) -> bool:
    x1, y1, x2, y2 = seg
    # Cheap rejects first: a segment whose bbox misses the rect cannot hit it.
    if max(x1, x2) < left or min(x1, x2) > right:
        return False
    if max(y1, y2) < top or min(y1, y2) > bottom:
        return False
    # Either endpoint inside the rect is an immediate hit (covers the case of a
    # segment lying wholly within the card).
    if left <= x1 <= right and top <= y1 <= bottom:
        return True
    if left <= x2 <= right and top <= y2 <= bottom:
        return True
    # Otherwise the segment must cross one of the rect's edges.
    edges = (
        (left, top, right, top),
        (right, top, right, bottom),
        (right, bottom, left, bottom),
        (left, bottom, left, top),
    )
    return any(_segments_cross(seg, edge) for edge in edges)
