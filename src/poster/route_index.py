"""Spatial index for testing whether a rectangle covers the trip's track.

Poster cards that land on top of the route are the single most visible layout
failure: the track is the subject of the poster, and a card sitting across it
hides the very thing the reader is following. Card placement therefore needs a
cheap "does this rectangle touch the route?" query.

A full A0 render projects hundreds of thousands of track points, and placement
evaluates dozens of candidate rectangles per pin, so a linear scan over every
segment per query is far too slow. This module buckets segments into a grid
once, then answers each query against only the segments in the cells the
rectangle actually covers. The grid subdivides recursively wherever segments
cluster densely (e.g. a revisited location), so no single cell size has to
fit both the sparse majority of a route and its few extremely dense spots.

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


def _cells_for_bbox(cell: float, left: float, top: float, right: float, bottom: float):
    cx0 = int(left // cell)
    cx1 = int(right // cell)
    cy0 = int(top // cell)
    cy1 = int(bottom // cell)
    for cy in range(cy0, cy1 + 1):
        for cx in range(cx0, cx1 + 1):
            yield (cx, cy)


# A real trip can revisit the same handful of places many times over (a city
# stayed in twice, a hub airport, a loop route) — its track then has both
# long sparse stretches and a few pixel-scale hotspots where thousands of
# segments land in the same small area. No single uniform cell size fits
# both: coarse enough for the sparse majority means the hotspot's cell holds
# nearly the whole route (this once took a real production render's card
# placement past the 10-minute job timeout); fine enough for the hotspot
# means a huge, mostly-empty cell table for the sparse majority. `_GridNode`
# fixes this by subdividing recursively: any cell whose segment count is
# still over `_MAX_SEGMENTS_PER_CELL` gets replaced with a nested, finer
# node scoped to just that cell's own segments, instead of growing an
# unbounded flat bucket.
_MAX_SEGMENTS_PER_CELL = 64
_MIN_CELL_SIZE = 2.0
_MAX_DEPTH = 8
_SUBDIVIDE_FACTOR = 4.0

# A segment whose bbox spans more than this many cells at a node's own cell
# size would, if bucketed normally, get added to that many cells — and the
# same again at every finer level a hot cell recurses into. A dense cluster
# is not just many segments close together; a hub city's track can also
# have a few long "passing through" segments crossing it, and repeatedly
# fanning those out across an ever-finer grid is what actually blows up
# construction cost, independent of how many segments there are. Past this
# span, subdividing the cell further would not meaningfully separate the
# segment from its neighbours anyway, so it goes into the node's flat
# `overflow` list instead — checked once per query into this node, not
# rebucketed at every recursion level.
_MAX_SPAN_CELLS = 4.0


class _GridNode:
    """One level of the recursive grid. A bucket is either a flat list of
    segment indices (a leaf) or a nested, finer `_GridNode` (a hotspot that
    was split further). `overflow` holds segments too long, relative to this
    node's own cell size, for subdivision to help with."""

    __slots__ = ("cell", "buckets", "overflow")

    def __init__(self, segments: List[Segment], indices: Sequence[int], cell: float, depth: int):
        self.cell = cell
        long_span = cell * _MAX_SPAN_CELLS
        self.overflow: List[int] = []
        raw: Dict[Tuple[int, int], List[int]] = {}
        for i in indices:
            seg = segments[i]
            left, top = min(seg[0], seg[2]), min(seg[1], seg[3])
            right, bottom = max(seg[0], seg[2]), max(seg[1], seg[3])
            if max(right - left, bottom - top) > long_span:
                self.overflow.append(i)
                continue
            for key in _cells_for_bbox(cell, left, top, right, bottom):
                raw.setdefault(key, []).append(i)

        self.buckets: Dict[Tuple[int, int], object] = {}
        can_subdivide = cell > _MIN_CELL_SIZE and depth < _MAX_DEPTH
        for key, idxs in raw.items():
            if len(idxs) > _MAX_SEGMENTS_PER_CELL and can_subdivide:
                self.buckets[key] = _GridNode(segments, idxs, cell / _SUBDIVIDE_FACTOR, depth + 1)
            else:
                self.buckets[key] = idxs

    def collect(self, left: float, top: float, right: float, bottom: float, found: Set[int]) -> None:
        if self.overflow:
            found.update(self.overflow)
        for key in _cells_for_bbox(self.cell, left, top, right, bottom):
            bucket = self.buckets.get(key)
            if bucket is None:
                continue
            if isinstance(bucket, _GridNode):
                # Clip the query to this cell's own extent before recursing.
                # Without this, a child node would re-scan the *entire*
                # original query rect at its own finer cell size — and every
                # sibling cell that also happens to hold a child node would
                # redundantly do the same for the same query, so the number
                # of (child) cells visited would grow with the query rect's
                # area divided by the finest cell size, not with how much of
                # that area this particular child actually covers.
                cx, cy = key
                cell = self.cell
                bucket.collect(
                    max(left, cx * cell), max(top, cy * cell),
                    min(right, (cx + 1) * cell), min(bottom, (cy + 1) * cell),
                    found,
                )
            else:
                found.update(bucket)


class RouteIndex:
    """Recursively-subdivided grid index over the projected route's segments."""

    def __init__(
        self,
        polylines: Iterable[Sequence[Point]],
        canvas_size: Tuple[int, int],
        cell_size: float | None = None,
    ):
        self.segments = _segments_from_polylines(polylines)
        canvas_w, canvas_h = canvas_size
        # A cell around a card's own size keeps the number of cells a query
        # touches small while keeping per-cell segment lists short — this is
        # the starting cell size; any cell that turns out to be a hotspot is
        # subdivided further by `_GridNode`.
        self.cell = float(cell_size or max(32.0, max(canvas_w, canvas_h) / 64.0))
        self._root = _GridNode(self.segments, range(len(self.segments)), self.cell, 0)

    def __bool__(self) -> bool:
        return bool(self.segments)

    def _candidate_indices(self, left: float, top: float, right: float, bottom: float) -> Set[int]:
        found: Set[int] = set()
        self._root.collect(left, top, right, bottom, found)
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
