"""Pure geometry helpers for editing an activity's track (issue #31).

Two responsibilities, both side-effect-free and standalone-testable:

1. **Canonical point list** — align ``summary_polyline`` (full-resolution track,
   every latlng re-encoded) with the parallel ``elevation_profile``
   (``distances_km`` / ``elevations_m``) into one ordered list of
   ``TrackPoint(lat, lng, elev)``.  Elevation is interpolated onto the polyline
   points by cumulative distance, since the two arrays are not guaranteed to be
   index-aligned.  ``points_to_polyline`` / ``points_to_elevation_profile``
   re-derive the storage arrays after an edit.

2. **Metric recomputation** — :func:`recompute_track_metrics` derives distance,
   elevation gain, hi/lo, start/end latlng, average speed, and *apportioned*
   moving/elapsed times for an edited (trimmed / split / point-edited) piece.
   Times are apportioned proportionally to retained distance because no
   per-point time stream is stored (only scalar times survive enrichment).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Tuple

import polyline as polyline_lib

from src.models.great_circle import haversine_km


@dataclass
class TrackPoint:
    lat: float
    lng: float
    elev: Optional[float] = None


def align_points(
    summary_polyline: Optional[str],
    elevation_profile: Optional[Tuple[List[float], List[float]]],
) -> List[TrackPoint]:
    """Align a polyline and an elevation profile into one ordered point list.

    Elevation values are interpolated onto the decoded polyline points by
    cumulative haversine distance.  When no elevation profile is present the
    points carry ``elev=None``.
    """
    if not summary_polyline:
        return []
    decoded = polyline_lib.decode(summary_polyline)  # [(lat, lng), …]
    if not decoded:
        return []

    dist_km: List[float] = []
    elev_m: List[float] = []
    if elevation_profile:
        dist_km, elev_m = elevation_profile[0] or [], elevation_profile[1] or []

    if not dist_km or not elev_m or len(dist_km) != len(elev_m):
        return [TrackPoint(lat=lat, lng=lng, elev=None) for lat, lng in decoded]

    # Cumulative distance (km) along the decoded polyline.
    cum: List[float] = [0.0]
    for i in range(1, len(decoded)):
        cum.append(cum[-1] + haversine_km(
            decoded[i - 1][0], decoded[i - 1][1], decoded[i][0], decoded[i][1]))

    points: List[TrackPoint] = []
    for (lat, lng), d in zip(decoded, cum):
        points.append(TrackPoint(lat=lat, lng=lng, elev=_interp_elev(d, dist_km, elev_m)))
    return points


def _interp_elev(d: float, dist_km: List[float], elev_m: List[float]) -> float:
    """Linearly interpolate elevation at cumulative distance *d* (km)."""
    if d <= dist_km[0]:
        return elev_m[0]
    if d >= dist_km[-1]:
        return elev_m[-1]
    # Binary search would be faster, but linear is fine for the point counts
    # involved and keeps the code obvious.
    for i in range(1, len(dist_km)):
        if d <= dist_km[i]:
            d0, d1 = dist_km[i - 1], dist_km[i]
            e0, e1 = elev_m[i - 1], elev_m[i]
            if d1 == d0:
                return e0
            frac = (d - d0) / (d1 - d0)
            return e0 + frac * (e1 - e0)
    return elev_m[-1]


def points_to_polyline(points: List[TrackPoint]) -> Optional[str]:
    """Re-encode an ordered point list to a Google-encoded polyline string."""
    if not points:
        return None
    return polyline_lib.encode([(p.lat, p.lng) for p in points])


def points_to_elevation_profile(
    points: List[TrackPoint],
) -> Optional[Tuple[List[float], List[float]]]:
    """Re-derive ``(distances_km, elevations_m)`` from an ordered point list.

    Returns ``None`` when no point carries an elevation value (so the caller
    stores no elevation profile rather than a degenerate all-None one).
    """
    if not points or all(p.elev is None for p in points):
        return None
    distances: List[float] = [0.0]
    for i in range(1, len(points)):
        distances.append(distances[-1] + haversine_km(
            points[i - 1].lat, points[i - 1].lng, points[i].lat, points[i].lng))
    elevations = [p.elev if p.elev is not None else 0.0 for p in points]
    return distances, elevations


@dataclass
class TrackMetrics:
    distance: float               # metres
    total_elevation_gain: float   # metres
    elev_high: Optional[float]
    elev_low: Optional[float]
    start_latlng: Optional[List[float]]
    end_latlng: Optional[List[float]]
    average_speed: float          # m/s
    moving_time: int              # seconds (apportioned)
    elapsed_time: int             # seconds (apportioned)


def recompute_track_metrics(
    points: List[TrackPoint],
    *,
    original_distance_m: float = 0.0,
    original_moving_time: int = 0,
    original_elapsed_time: int = 0,
) -> TrackMetrics:
    """Recompute an activity's scalar metrics from an edited point list.

    ``original_*`` are the pre-edit distance / times; moving and elapsed times
    are apportioned to the fraction of the original distance retained (no
    per-point time stream exists, so proportional-to-distance is the best
    available estimate).  Degenerate inputs (0 or 1 point) yield all-zero
    metrics with ``None`` latlngs/elevations.
    """
    if len(points) < 2:
        start = ([points[0].lat, points[0].lng] if points else None)
        end = start
        elev = points[0].elev if points else None
        return TrackMetrics(
            distance=0.0,
            total_elevation_gain=0.0,
            elev_high=elev,
            elev_low=elev,
            start_latlng=start,
            end_latlng=end,
            average_speed=0.0,
            moving_time=0,
            elapsed_time=0,
        )

    distance_km = 0.0
    for i in range(1, len(points)):
        distance_km += haversine_km(
            points[i - 1].lat, points[i - 1].lng, points[i].lat, points[i].lng)
    distance_m = distance_km * 1000.0

    elevs = [p.elev for p in points if p.elev is not None]
    gain = 0.0
    prev: Optional[float] = None
    for p in points:
        if p.elev is None:
            continue
        if prev is not None and p.elev > prev:
            gain += p.elev - prev
        prev = p.elev
    elev_high = max(elevs) if elevs else None
    elev_low = min(elevs) if elevs else None

    # Apportion times proportionally to retained distance.
    if original_distance_m > 0:
        frac = max(0.0, min(1.0, distance_m / original_distance_m))
    else:
        frac = 1.0
    moving_time = int(round(original_moving_time * frac))
    elapsed_time = int(round(original_elapsed_time * frac))

    average_speed = distance_m / moving_time if moving_time > 0 else 0.0

    return TrackMetrics(
        distance=distance_m,
        total_elevation_gain=gain,
        elev_high=elev_high,
        elev_low=elev_low,
        start_latlng=[points[0].lat, points[0].lng],
        end_latlng=[points[-1].lat, points[-1].lng],
        average_speed=average_speed,
        moving_time=moving_time,
        elapsed_time=elapsed_time,
    )
