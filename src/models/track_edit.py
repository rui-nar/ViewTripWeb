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

from bisect import bisect_left
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
    """Linearly interpolate elevation at cumulative distance *d* (km).

    Uses a binary search rather than a linear scan: called once per polyline
    point from align_points, a linear rescan-from-start made a full alignment
    O(N*M) (N polyline points, M elevation samples) — quadratic overall since
    N and M scale together, which measured at 20+ seconds for a ~40k-point
    activity (a few hours of dense GPS recording) and blew past the client's
    request timeout on save/split (issue #45).
    """
    if d <= dist_km[0]:
        return elev_m[0]
    if d >= dist_km[-1]:
        return elev_m[-1]
    i = bisect_left(dist_km, d)
    d0, d1 = dist_km[i - 1], dist_km[i]
    e0, e1 = elev_m[i - 1], elev_m[i]
    if d1 == d0:
        return e0
    frac = (d - d0) / (d1 - d0)
    return e0 + frac * (e1 - e0)


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


#: Half-width, in samples, of the centred moving average applied to elevations
#: before gain is accumulated. ±5 (an 11-sample window) flattens per-sample GPS
#: and barometric jitter without eating a real climb, which spans hundreds of
#: samples at any normal recording rate.
ELEV_SMOOTH_HALF_WINDOW = 5

#: Metres a smoothed elevation must move away from the last counted reference
#: before that move is treated as real ascent rather than drift.
ELEV_GAIN_THRESHOLD_M = 3.0

#: Below this many samples the moving average is skipped entirely — see
#: :func:`_smooth_elevations`. Four times the half-window: enough series either
#: side of a feature for the average to filter it rather than swallow it.
ELEV_SMOOTH_MIN_SAMPLES = 4 * ELEV_SMOOTH_HALF_WINDOW


def _smooth_elevations(elevations: List[float]) -> List[float]:
    """Centred moving average over ``ELEV_SMOOTH_HALF_WINDOW`` samples either side.

    The window is clamped at both ends rather than padded, so the first and last
    samples average over whatever neighbours exist. Endpoints therefore keep
    slightly more of their own noise than the middle does — immaterial for a
    gain figure accumulated over the whole track.

    Series shorter than :data:`ELEV_SMOOTH_MIN_SAMPLES` are returned untouched.
    A window that spans a large fraction of the series does not filter it, it
    erases it: averaging four samples of 100/150/120/170 m yields four identical
    values and a gain of zero, when every step there is real. Below that length
    the hysteresis band in :func:`elevation_gain` carries the whole job — the
    absolute error it can leave over so few samples is metres.
    """
    n = len(elevations)
    if n < ELEV_SMOOTH_MIN_SAMPLES:
        return list(elevations)
    w = ELEV_SMOOTH_HALF_WINDOW
    out: List[float] = []
    for i in range(n):
        a = max(0, i - w)
        b = min(n, i + w + 1)
        out.append(sum(elevations[a:b]) / (b - a))
    return out


def elevation_gain(elevations: List[float]) -> float:
    """Total ascent in metres over an ordered elevation series.

    Summing every positive sample-to-sample delta — which is what this did until
    issue #260 — counts sensor noise as climbing. Every upward flicker is added
    and no downward one subtracts it, so the error accumulates in one direction
    and grows with the sample count. On a 6000-sample track with a true 600 m
    climb and ±1.2 m of ordinary GPS/barometric noise it reported 4094 m.

    So: smooth first (:func:`_smooth_elevations`), then accumulate with a
    hysteresis band. ``ref`` is the last elevation counted; a rise is only booked
    once the series climbs ``ELEV_GAIN_THRESHOLD_M`` above it, and ``ref`` only
    follows the series down once it falls that far below. Movement inside the
    band is drift and is ignored. The same fixture then reports 598 m.

    Both halves are needed. Smoothing alone leaves 644 m of residual jitter on
    that fixture; the threshold alone leaves 1175 m, because noise still crosses
    a 3 m band often enough over thousands of samples to matter.

    Strava-synced activities never reach here — their ``total_elevation_gain``
    arrives already processed. This is the figure for tracks we derive
    ourselves: hand-edited pieces, splits, and GPX imports.
    """
    if len(elevations) < 2:
        return 0.0
    smoothed = _smooth_elevations(elevations)
    gain = 0.0
    ref = smoothed[0]
    for value in smoothed[1:]:
        if value - ref >= ELEV_GAIN_THRESHOLD_M:
            gain += value - ref
            ref = value
        elif ref - value >= ELEV_GAIN_THRESHOLD_M:
            ref = value
    return gain


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
    gain = elevation_gain(elevs)
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
