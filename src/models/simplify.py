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


# Web Mercator cannot represent the poles; this is the latitude the standard
# tile grid stops at.
_MAX_MERCATOR_LAT = 85.05112878


def _lon_to_tile_x(lon: float, n: int) -> float:
    return (lon + 180.0) / 360.0 * n


def _lat_to_tile_y(lat: float, n: int) -> float:
    lat = min(max(lat, -_MAX_MERCATOR_LAT), _MAX_MERCATOR_LAT)
    r = math.radians(lat)
    return (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n


def _tile_x_to_lon(x: float, n: int) -> float:
    return x / n * 360.0 - 180.0


def _tile_y_to_lat(y: float, n: int) -> float:
    return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))


def snap_bbox_to_tiles(bbox: tuple, zoom: int) -> tuple:
    """Snap *bbox* OUTWARD to whole Web Mercator tiles at *zoom*.

    Returns ``(snapped_bbox, tile_range)`` where both are
    ``(min_lon, min_lat, max_lon, max_lat)`` and ``(x0, y0, x1, y1)``.

    This exists to bound cache keys. A viewport is a pair of floats that
    changes on every pan pixel, so keying a payload cache on the raw box mints
    an entry per pixel — and this project has already OOM-killed its API
    container once with a payload cache bounded by the wrong thing (issue
    #209's third incident, and again from the client side in #276). Snapping to
    the tile grid the zoom already defines makes neighbouring viewports share
    an entry, and makes the key an integer tuple rather than four floats.

    Snapping outward, never inward: the response must be a superset of what was
    asked for, or the caller draws a gap at the edge of its screen. It also
    pads for free — up to a tile on each side, which is the same reason the
    client can pan a little without refetching.

    The server snaps whatever it is given rather than trusting the client to
    have snapped: an older or hostile client sending raw floats must not be
    able to mint unbounded cache entries.
    """
    min_lon, min_lat, max_lon, max_lat = bbox
    n = 2 ** int(zoom)
    x0 = max(0, min(n, math.floor(_lon_to_tile_x(min_lon, n))))
    x1 = max(0, min(n, math.ceil(_lon_to_tile_x(max_lon, n))))
    # Tile y grows southward, so the box's max latitude is its min y.
    y0 = max(0, min(n, math.floor(_lat_to_tile_y(max_lat, n))))
    y1 = max(0, min(n, math.ceil(_lat_to_tile_y(min_lat, n))))
    # A viewport thinner than a tile lands on one boundary twice; widen it to a
    # whole tile so the box is never empty.
    if x1 == x0:
        x1 = min(n, x0 + 1) if x0 < n else n
        x0 = x1 - 1
    if y1 == y0:
        y1 = min(n, y0 + 1) if y0 < n else n
        y0 = y1 - 1
    snapped = (
        _tile_x_to_lon(x0, n),
        _tile_y_to_lat(y1, n),
        _tile_x_to_lon(x1, n),
        _tile_y_to_lat(y0, n),
    )
    return snapped, (x0, y0, x1, y1)


def line_bbox(poly: list) -> tuple:
    """``(min_lon, min_lat, max_lon, max_lat)`` of a ``[lon, lat]`` polyline.

    Indexed, not unpacked, for the same reason :func:`simplify_lonlat` is:
    GeoJSON positions legally carry a third element.
    """
    lons = [p[0] for p in poly]
    lats = [p[1] for p in poly]
    return (min(lons), min(lats), max(lons), max(lats))


def bboxes_intersect(a: tuple, b: tuple) -> bool:
    """Whether two ``(min_lon, min_lat, max_lon, max_lat)`` boxes overlap.

    Touching counts as overlapping: a track running exactly along the edge of
    the viewport is on screen.
    """
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


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


def _line_touches(poly: list, bbox: tuple) -> bool:
    """Whether *poly* is at all inside *bbox*, cheaply for the common answer.

    :func:`line_bbox` walks every coordinate, and at whole-trip zoom — where
    every line is on screen and the box removes nothing — that pass is pure
    added cost: measured at 0.24 s to 0.34 s for a 219-activity, 1.47 M-point
    trip. Testing the first point first makes the "on screen" answer O(1),
    which is the answer for every line in exactly that case. A line whose first
    point is outside still pays the full walk, and there the walk buys the
    Ramer-Douglas-Peucker pass being skipped, which is orders of magnitude
    more.
    """
    first = poly[0]
    if bbox[0] <= first[0] <= bbox[2] and bbox[1] <= first[1] <= bbox[3]:
        return True
    return bboxes_intersect(line_bbox(poly), bbox)


def restrict_to_bbox(poly: list, bbox: tuple | None, *, min_points: int = 32) -> list:
    """Reduce a line that cannot be seen in *bbox* to the ``min_points`` floor.

    The same reduction :func:`simplify_for_zoom` applies when given a box, but
    as a *separate* pass so it can run over an already-simplified line.

    That separation is the point. Simplifying with the box folded in produces a
    result that is only valid for that one box, so every pan to a new box paid
    a full rebuild — and a rebuild is dominated by decoding every activity's
    polyline (measured 1.83 s for a 219-activity trip) plus the
    Ramer-Douglas-Peucker pass, not by the box. Simplifying *without* the box
    yields one result per zoom level that every box can be served from.

    Flooring an already-simplified line rather than the original gives the same
    point count and the same endpoints, from geometry that is off screen by
    definition. Lines that *are* visible are untouched here, so what the user
    can actually see is identical either way.
    """
    if bbox is None or len(poly) <= min_points or _line_touches(poly, bbox):
        return poly
    return _stride_to(poly, min_points)


def simplify_for_zoom(
    poly: list,
    zoom: float,
    *,
    min_points: int = 32,
    max_input_points: int = 4000,
    bbox: tuple | None = None,
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
      tolerance: its budget at the time (``kMaxTotalPolylinePoints``, then
      6000) worked out at ~27 points per activity for this trip, and that was
      already being described as straight lines. A floor below what the
      renderer would have drawn anyway is a regression however defensible the
      arithmetic. That budget has since been raised to 40,000 precisely so it
      stops competing with this function (issue #276); the floor stays where it
      is because it is the resolution at which a leg stops reading as a
      straight line, which has nothing to do with the client's valve.

    ``bbox``, when given, marks the region the client can actually see. A line
    outside it is reduced to the ``min_points`` floor and skips simplification
    altogether — see the branch below.
    """
    if len(poly) < 3:
        return poly
    if bbox is not None and not _line_touches(poly, bbox):
        # Off screen. Give it exactly the resolution a whole-trip zoom would
        # have given it — the min_points floor below — and skip the RDP pass
        # entirely. That equivalence is the whole safety argument for the
        # bounding box: the feature is still present, still carries its
        # properties and its endpoints, and is no coarser than something the
        # client already renders and exports at another zoom. Dropping the
        # feature instead would have broken the segment-overlay reconciliation,
        # fit-to-bounds and the whole-trip elevation cursor, all of which read
        # `geo` as a description of the entire trip.
        return _stride_to(poly, min(min_points, len(poly)))
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
