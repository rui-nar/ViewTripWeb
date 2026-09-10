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


#: Distance, in metres of travel, spanned by the centred moving average applied
#: to elevations before gain is accumulated. Measured in DISTANCE, not samples:
#: a fixed sample count means a window whose real width depends entirely on the
#: recording rate. An 11-sample window is ~60 m of a 1 Hz ride and a full
#: kilometre of a route exported at one point per 100 m, which erased every hill
#: on planned-route GPX — reporting 3 m of climb on a route with 600 m of it.
ELEV_SMOOTH_SPAN_M = 60.0

#: Multiple of the estimated residual noise used as the hysteresis band, and the
#: floor/ceiling it is clamped to. A fixed band cannot serve both inputs we get:
#: on noise-free DEM elevations (planned routes) anything above ~1 m simply
#: discards real rollers, while on a bad GPS fix even 3 m leaks phantom ascent.
ELEV_NOISE_SIGMA_MULTIPLE = 3.0
ELEV_GAIN_THRESHOLD_MIN_M = 1.0
ELEV_GAIN_THRESHOLD_MAX_M = 5.0

#: Independent per-sample noise of sigma appears in a series' second
#: differences at ``sigma * sqrt(6)``; dividing it back out recovers sigma.
_SECOND_DIFFERENCE_NOISE_FACTOR = 6 ** 0.5


def _smooth_elevations(
    elevations: List[float], distances_km: Optional[List[float]]
) -> List[float]:
    """Centred moving average spanning ``ELEV_SMOOTH_SPAN_M`` of travel.

    Two properties matter, and both come from measuring the window in distance
    rather than in samples:

    * Sample rate stops mattering. The same terrain recorded at 1 Hz and at one
      point per 100 m gets the same physical amount of filtering.
    * Sparse series are left alone. When the median gap between samples already
      exceeds half the span there is nothing to average — such a series is a
      route planner's DEM output, which carries no sensor noise to remove, and
      averaging it would only flatten real terrain.

    The window is clamped at both ends rather than padded, so the first and last
    samples average over whatever neighbours exist. Endpoints therefore keep
    slightly more of their own noise than the middle does — immaterial for a
    gain figure accumulated over the whole track.

    Without ``distances_km`` (a caller that has elevations only) the series is
    returned untouched: a guessed window is worse than none, and the adaptive
    band in :func:`elevation_gain` still rejects noise.
    """
    n = len(elevations)
    if n < 3 or not distances_km or len(distances_km) != n:
        return list(elevations)

    half_km = (ELEV_SMOOTH_SPAN_M / 2.0) / 1000.0
    gaps = sorted(distances_km[i + 1] - distances_km[i] for i in range(n - 1))
    if gaps[len(gaps) // 2] >= half_km:
        return list(elevations)

    # Prefix sums so each window costs one subtraction rather than re-adding its
    # members: the window holds ~11 samples of a 1 Hz ride but ~60 of a track
    # recorded every metre, and re-summing made the whole pass O(n * window).
    prefix: List[float] = [0.0]
    for value in elevations:
        prefix.append(prefix[-1] + value)

    out: List[float] = []
    lo = hi = 0
    for i in range(n):
        while distances_km[i] - distances_km[lo] > half_km:
            lo += 1
        while hi + 1 < n and distances_km[hi + 1] - distances_km[i] <= half_km:
            hi += 1
        out.append((prefix[hi + 1] - prefix[lo]) / (hi + 1 - lo))
    return out


def _noise_threshold(elevations: List[float]) -> float:
    """Hysteresis band, sized from how noisy this particular series is.

    Noise is estimated from SECOND differences. A smooth series — a DEM-sampled
    planned route, or any real slope — bends slowly, so its second differences
    are near zero however steep it is; independent per-sample noise of sigma
    shows up in them at ``sigma * sqrt(6)``. Dividing that back out turns them
    into a sigma estimate that does not mistake a steep climb for jitter. The
    median absolute value (scaled by 1.4826, as for a Gaussian) is used rather
    than a mean so a handful of genuine cliffs cannot inflate it.

    Deliberately not measured against the smoothed series: smoothing is skipped
    for sparse input, and a residual of zero would then read as "no noise" and
    drop the band to its floor — which is right for a clean route export and
    very wrong for a sparsely recorded GPS track.

    Clamped: never below :data:`ELEV_GAIN_THRESHOLD_MIN_M`, so a perfectly clean
    series still ignores floating-point dust, and never above
    :data:`ELEV_GAIN_THRESHOLD_MAX_M`, so a catastrophically noisy one cannot
    raise the band until real mountains fit inside it.
    """
    if len(elevations) < 3:
        return ELEV_GAIN_THRESHOLD_MIN_M
    second = sorted(
        abs(elevations[i + 1] - 2 * elevations[i] + elevations[i - 1])
        for i in range(1, len(elevations) - 1)
    )
    mad = second[len(second) // 2]
    sigma = 1.4826 * mad / _SECOND_DIFFERENCE_NOISE_FACTOR
    return min(ELEV_GAIN_THRESHOLD_MAX_M,
               max(ELEV_GAIN_THRESHOLD_MIN_M, ELEV_NOISE_SIGMA_MULTIPLE * sigma))


def elevation_gain(
    elevations: List[float], distances_km: Optional[List[float]] = None
) -> float:
    """Total ascent in metres over an ordered elevation series.

    Summing every positive sample-to-sample delta — which is what this did until
    issue #260 — counts sensor noise as climbing. Every upward flicker is added
    and no downward one subtracts it, so the error accumulates in one direction
    and grows with the sample count. On a 6000-sample track with a true 600 m
    climb and ±1.2 m of ordinary GPS/barometric noise it reported 4094 m.

    So: smooth over a fixed distance (:func:`_smooth_elevations`), then
    accumulate through a hysteresis band sized from the noise that smoothing
    just removed (:func:`_noise_threshold`). ``ref`` is the last elevation
    counted; a rise is booked only once the series climbs a band above it, and
    ``ref`` only follows the series down once it falls a band below. Movement
    inside the band is drift. That fixture then reports 596 m.

    Both halves are needed, and both must adapt to the input, because the two
    kinds of file this app ingests are opposites. A 1 Hz recording is dense and
    noisy: it needs real filtering and a wide band. A planned route exported
    from Komoot or RideWithGPS is sparse and noise-free: it needs no filtering
    at all, and a wide band would throw away every roller it contains.

    ``distances_km`` is the cumulative distance of each sample, and is what
    makes the window physical rather than a function of the recording rate.

    Strava-synced activities never reach here — their ``total_elevation_gain``
    arrives already processed. This is the figure for tracks we derive
    ourselves: hand-edited pieces, splits, and GPX imports.
    """
    if len(elevations) < 2:
        return 0.0
    smoothed = _smooth_elevations(elevations, distances_km)
    threshold = _noise_threshold(elevations)
    gain = 0.0
    ref = smoothed[0]
    for value in smoothed[1:]:
        if value - ref >= threshold:
            gain += value - ref
            ref = value
        elif ref - value >= threshold:
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

    # Cumulative distance is accumulated over EVERY point, but only recorded
    # alongside points that carry an elevation — so a stretch recorded without
    # one leaves a real gap in the series the smoothing window can see, rather
    # than two distant samples looking adjacent.
    distance_km = 0.0
    elevs: List[float] = []
    elev_dist_km: List[float] = []
    if points[0].elev is not None:
        elevs.append(points[0].elev)
        elev_dist_km.append(0.0)
    for i in range(1, len(points)):
        distance_km += haversine_km(
            points[i - 1].lat, points[i - 1].lng, points[i].lat, points[i].lng)
        if points[i].elev is not None:
            elevs.append(points[i].elev)
            elev_dist_km.append(distance_km)
    distance_m = distance_km * 1000.0

    gain = elevation_gain(elevs, elev_dist_km)
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
