"""Ramer-Douglas-Peucker simplification for lon/lat polylines.

Moved here from ``src/services/hafas_service.py`` (where it trimmed MOTIS
shape points) so the geo endpoints can use the same implementation for
zoom-appropriate level of detail — issue #295. One carefully-reasoned
projection correction is easier to keep right in one place than in two.

The motivating measurement: a 219-activity trip's full-resolution geometry is
1,465,345 coordinates, and the map renders 6,051 of them. The client holds all
1.47 M — roughly 180 MB of Dart heap, on a device where the heap plateaus at
~625 MB and the process is killed above ~1.3 GB. Sending geometry matched to
the zoom the user is actually looking at removes the difference rather than
decimating it away after the fact.
"""
from __future__ import annotations

import math

# Metres per pixel at zoom 0 on the equator, for 256 px tiles — the standard
# Web Mercator constant, and the basis for turning a zoom level into a
# simplification tolerance.
_EQUATOR_M_PER_PX_Z0 = 156543.03392


def zoom_tolerance_m(zoom: float, latitude: float) -> float:
    """Roughly one screen pixel at *zoom*, at *latitude*.

    Simplifying to a pixel is the point: anything finer cannot be seen, and
    the difference between "cannot be seen" and "was never sent" is the whole
    saving. Latitude matters because Web Mercator stretches: at 60 degrees a
    pixel covers half the ground distance it does at the equator, so a
    latitude-blind tolerance would visibly over-simplify northern tracks.
    """
    scale = max(math.cos(math.radians(latitude)), 0.01)
    return _EQUATOR_M_PER_PX_Z0 * scale / (2 ** zoom)


def midpoint_latitude(poly: list) -> float:
    """The latitude :func:`simplify_lonlat` projects against.

    Exposed so a caller choosing a tolerance uses the *same* latitude the
    simplification will. Taking it from the first point instead means a
    feature spanning 0 to 60 degrees is simplified at up to twice the intended
    tolerance along its northern half — precisely the error the latitude term
    exists to prevent.
    """
    return (poly[0][1] + poly[-1][1]) / 2


def _stride_to(poly: list, target: int) -> list:
    """Uniformly reduce *poly* to at most *target* points, keeping both ends.

    A cheap O(n) pre-pass so the O(n log n) RDP below runs over a bounded
    working set. Straight Ramer-Douglas-Peucker over a 219-activity trip's
    1.47 M points measured **21.6 s per request** in pure Python — the
    endpoint was slower than the full-resolution one it replaced.

    This does cost the strict RDP guarantee (every dropped point provably
    within tolerance of the line replacing it) for inputs above the cap: a
    strided point could in principle sit further out. At a GPS sample every
    few metres against a tolerance of hundreds, that is not a distinction the
    screen can render.
    """
    if len(poly) <= target or target < 2:
        return poly
    step = (len(poly) - 1) / (target - 1)
    out = [poly[0]]
    for i in range(1, target - 1):
        out.append(poly[round(i * step)])
    out.append(poly[-1])
    return out


def simplify_for_zoom(
    poly: list,
    zoom: float,
    *,
    min_points: int = 32,
    max_input_points: int = 4000,
) -> list:
    """Simplify *poly* for *zoom*, bounded in both cost and coarseness.

    Two guards the plain tolerance-based call needs in production:

    * ``max_input_points`` bounds the work — see :func:`_stride_to`.
    * ``min_points`` bounds the *result*. At whole-trip zoom a pixel covers
      hundreds of metres, and RDP legitimately collapses an activity to its
      two endpoints: measured, a 219-activity trip came back as 515
      coordinates — 2.4 per activity, a straight line per leg. Correct by the
      tolerance, useless as a map. Below the floor the line is strided to it
      instead, keeping its shape at a resolution the eye can still read.

      32 is chosen against what the client renders, not against the
      tolerance: its own budget (``kMaxTotalPolylinePoints``, 6000) worked out
      at ~27 points per activity for this trip, and that was already being
      described as straight lines. A floor below what the renderer would have
      drawn anyway is a regression however defensible the arithmetic.
    """
    if len(poly) < 3:
        return poly
    working = _stride_to(poly, max_input_points)
    reduced = simplify_lonlat(working, zoom_tolerance_m(zoom, midpoint_latitude(working)))
    if len(reduced) >= min_points:
        return reduced
    return _stride_to(working, min(min_points, len(working)))


def simplify_lonlat(poly: list, tolerance_m: float) -> list:
    """Ramer-Douglas-Peucker: drop points within *tolerance_m* of the line
    their neighbours already describe.

    Iterative, not recursive: an 11k-point trip would otherwise risk blowing
    the stack.

    Distances are measured on a locally-equirectangular projection (longitude
    scaled by cos(latitude)) rather than on raw ``[lon, lat]`` degrees. A
    degree of longitude is only ~63% of a degree of latitude at European
    latitudes, so an unprojected epsilon silently allows up to ``1/cos`` times
    the tolerance north-south — measured at 3.10 m for a nominal 2 m on one
    real route. One scale factor is used for the whole line, so the effective
    tolerance still drifts a few percent across a long north-south route
    (measured 2.07 m for a nominal 2 m on ICE 75).

    Endpoints are always kept, so a simplified line still starts and ends
    exactly where the original did.
    """
    if len(poly) < 3 or tolerance_m <= 0:
        return poly
    scale = max(math.cos(math.radians(midpoint_latitude(poly))), 0.01)
    eps = tolerance_m / 111_000.0
    # Indexed, not unpacked: GeoJSON positions legally carry a third element
    # (elevation), and `for x, y in poly` raises ValueError on those.
    proj = [(p[0] * scale, p[1]) for p in poly]

    keep = [False] * len(poly)
    keep[0] = keep[-1] = True
    stack = [(0, len(poly) - 1)]
    while stack:
        i, j = stack.pop()
        if j - i < 2:
            continue
        ax, ay = proj[i]
        bx, by = proj[j]
        dx, dy = bx - ax, by - ay
        den = math.hypot(dx, dy)
        worst, at = -1.0, -1
        for k in range(i + 1, j):
            px, py = proj[k]
            if den == 0:
                dist = math.hypot(px - ax, py - ay)
            else:
                dist = abs(dy * px - dx * py + bx * ay - by * ax) / den
            if dist > worst:
                worst, at = dist, k
        if worst > eps:
            keep[at] = True
            stack.append((i, at))
            stack.append((at, j))
    return [p for p, k in zip(poly, keep) if k]
