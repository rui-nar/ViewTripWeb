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

import math
from bisect import bisect_left
from dataclasses import dataclass
from itertools import islice
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

    Points that carry no elevation are INTERPOLATED across, linearly by
    cumulative distance between the bracketing known samples; a gap at the very
    start or end extends the nearest known value. Until issue #374 they were
    stored as ``0.0``, which is a fabricated reading, not a missing one: a track
    through the Alps with three ``<ele>``-less points was stored as diving to
    sea level and climbing back out. Anything recomputing from that series read
    the dive as real — a 300-point track at ~500 m measured 12.1 m of gain on
    the live import path and 152.3 m recomputed from its own stored profile.
    The chart, which plots this array verbatim, drew the dive too.

    Interpolating rather than carrying ``None`` through the profile, because:

    * :func:`align_points` already interpolates by cumulative distance when it
      reads a profile back, so the value stored here is the value every reader
      would have derived anyway — the gap is filled once, consistently, instead
      of differently by each reader;
    * the array stays numeric, which is what the chart and the low-res
      downsample (``downsample_elevation``) require — carrying ``None`` means
      teaching every reader, client included, to skip holes;
    * it makes a recompute from storage agree with the live path.
      :func:`recompute_track_metrics` drops elevation-less points while still
      accumulating their distance, so it sees a straight run between the
      bracketing samples — exactly what the interpolated series holds.

    Returns ``None`` when no point carries an elevation value (so the caller
    stores no elevation profile rather than a degenerate all-None one).
    """
    if not points or all(p.elev is None for p in points):
        return None
    distances: List[float] = [0.0]
    for i in range(1, len(points)):
        distances.append(distances[-1] + haversine_km(
            points[i - 1].lat, points[i - 1].lng, points[i].lat, points[i].lng))
    return distances, interpolate_elevation_gaps(
        distances, [p.elev for p in points])


def interpolate_elevation_gaps(
    distances_km: List[float], elevations: List[Optional[float]],
) -> List[float]:
    """Fill the ``None`` holes in an elevation series, by cumulative distance.

    Interior gaps are a straight line between the bracketing known samples;
    a leading or trailing gap extends the nearest known value, there being
    nothing on the other side to aim at. Every element must be ``None`` or a
    number and at least one must be a number.

    Shared with the repair migration for issue #374, which maps the stored
    ``0.0`` sentinel back to ``None`` and calls this — so already-stored rows
    are repaired to exactly what the fixed writer would have produced.
    """
    known = [i for i, e in enumerate(elevations) if e is not None]
    if not known:
        raise ValueError("no point carries an elevation")
    filled: List[float] = [
        e if e is not None else 0.0 for e in elevations]  # holes overwritten below
    for i in range(known[0]):
        filled[i] = filled[known[0]]
    for i in range(known[-1] + 1, len(filled)):
        filled[i] = filled[known[-1]]
    for a, b in zip(known, known[1:]):
        if b == a + 1:
            continue
        d0, d1 = distances_km[a], distances_km[b]
        e0, e1 = filled[a], filled[b]
        span = d1 - d0
        for i in range(a + 1, b):
            frac = (distances_km[i] - d0) / span if span else 0.0
            filled[i] = e0 + frac * (e1 - e0)
    return filled


#: Distance, in metres of travel, spanned by the centred moving average applied
#: to elevations before gain is accumulated. Measured in DISTANCE, not samples:
#: a fixed sample count means a window whose real width depends entirely on the
#: recording rate. An 11-sample window is ~60 m of a 1 Hz ride and a full
#: kilometre of a route exported at one point per 100 m, which erased every hill
#: on planned-route GPX — reporting 3 m of climb on a route with 600 m of it.
#:
#: This is the FLOOR, not the width: a series noisy enough to need more gets a
#: wider window (see :func:`_smooth_elevations`), because 60 m of a track
#: sampled every 40 m holds a single point and averages nothing at all.
ELEV_SMOOTH_SPAN_M = 60.0

#: Ceiling on that widening. Past a few hundred metres a moving average stops
#: telling noise from terrain — a 240 m window already halves a 500 m roller —
#: so beyond this we stop filtering and let the hysteresis band absorb whatever
#: noise is left.
#:
#: Fixture, spelled out so the number can be re-derived: 30 sinusoidal hills of
#: 20 m over 600 m (12 km of track) sampled every 100 m under sigma 2 noise,
#: true ascent 600 m, mean of 20 noise seeds. This cap recovers 239 m
#: (218-254); letting the window widen without limit recovers 108 m (4-252) —
#: it swallows the hills outright on the noisier seeds.
ELEV_SMOOTH_MAX_SPAN_M = 240.0

#: Residual noise the window aims to leave behind, in metres. Averaging m
#: samples divides noise by sqrt(m), so this fixes how many samples the window
#: must hold: ``(sigma / target) ** 2``. Lower means more filtering and flatter
#: terrain, so this is the largest value that still clears the bar everywhere.
#: Over 20 noise seeds, 1.25 left 51 m of phantom climb on held-altitude flat
#: ground and 1.5 left 64 m on sparse flat ground; 1.0 caps both at 31 m. Going
#: below buys nothing — hill recovery is already identical at 1.25.
ELEV_SMOOTH_TARGET_SIGMA_M = 1.0

#: Multiple of the RESIDUAL noise — what survives smoothing, not what went in —
#: used as the hysteresis band, and the floor/ceiling it is clamped to. Sizing
#: it from the raw noise double-counts: smoothing already removed most of that,
#: and a band wide enough for unfiltered noise eats real rollers (20 m hills on
#: a sparse noisy track read 236 m of a true 600 that way, 349 m this way). A
#: smoothed series wanders rather than jitters, so the band has to cover the
#: largest excursion of a correlated series, not a one-sample outlier — several
#: sigma, not the 3x that suits per-sample jitter.
#:
#: Fixture: 30 km of flat ground sampled every 40 m under sigma 3 noise, true
#: ascent 0, mean (and worst) of 20 noise seeds. 3x leaves 25 m of phantom
#: climb (worst 52), 4x leaves 8 m (worst 35), this 4.5x leaves 3 m (worst 28),
#: 5x leaves 0 m (worst 7). The last step is not free: a wider band also eats
#: real rollers, and 4.5 is where flat ground is quiet without spending more
#: hill than it has to.
ELEV_NOISE_SIGMA_MULTIPLE = 4.5
ELEV_GAIN_THRESHOLD_MIN_M = 1.0
ELEV_GAIN_THRESHOLD_MAX_M = 20.0

#: Difference orders the noise estimate is taken over. See
#: :func:`_noise_estimate` for why the run starts at 3, and why the SMALLEST
#: estimate across it is the answer. Below this many differences a median of
#: them means nothing and the estimate is abandoned.
_NOISE_DIFFERENCE_ORDERS = range(3, 6)
_NOISE_MIN_DIFFERENCES = 8

#: Independent per-sample noise of sigma appears in a series' k-th differences
#: at ``sigma * sqrt(C(2k, k))`` — sqrt(20) for third differences, sqrt(70) for
#: fourth, sqrt(252) for fifth. Dividing it back out recovers sigma; the 1.4826
#: turns a median absolute deviation into a Gaussian standard deviation.
_NOISE_DIFFERENCE_SCALE = {
    k: 1.4826 / math.sqrt(math.comb(2 * k, k)) for k in _NOISE_DIFFERENCE_ORDERS
}

#: Most consecutive repeats treated as one altitude reading. Devices that update
#: altitude less often than position emit runs of identical values, and
#: differencing INSIDE such a run yields zero, hiding the noise completely.
_NOISE_MAX_RUN_STRIDE = 16

#: How many differences are actually sorted to take a median. A median over this
#: many is accurate to well under a percent, and sorting all 200k of a long ride
#: three times over cost 0.27 s of the 0.68 s a full pass took.
_NOISE_MEDIAN_SAMPLE_CAP = 20_000


def _run_stride(elevations: List[float]) -> int:
    """Samples per distinct altitude reading, as a median run length.

    A phone whose barometer updates at 0.2 Hz while position updates at 1 Hz
    writes each altitude five times over. Every difference taken inside such a
    run is exactly zero, so a median over differences collapses to zero and the
    series reads as noise-free — while the steps BETWEEN readings carry the full
    noise. Measured on 30 km of flat ground with altitude held for five samples,
    the band fell to its 1 m floor and reported 155 m of climb at sigma 1.2 and
    634 m at sigma 3. Differencing at this stride lands on separate readings.

    The median rather than the mean, so one long stationary stretch cannot
    stretch the stride for a whole track, and capped at
    :data:`_NOISE_MAX_RUN_STRIDE`. Ordinary quantisation — barometric altitude
    rounded to 0.1, 0.2 or 1 m — produces runs of one or two samples and so
    leaves the stride at 1, which is what keeps it out of this path.
    """
    counts = [0] * (_NOISE_MAX_RUN_STRIDE + 1)
    runs = 0
    length = 1
    for previous, current in zip(elevations, elevations[1:]):
        if previous == current:
            length += 1
        else:
            counts[length if length < _NOISE_MAX_RUN_STRIDE
                   else _NOISE_MAX_RUN_STRIDE] += 1
            runs += 1
            length = 1
    counts[length if length < _NOISE_MAX_RUN_STRIDE
           else _NOISE_MAX_RUN_STRIDE] += 1
    runs += 1

    seen = 0
    for stride in range(1, _NOISE_MAX_RUN_STRIDE + 1):
        seen += counts[stride]
        if seen * 2 > runs:
            return stride
    return _NOISE_MAX_RUN_STRIDE


def _noise_estimate(elevations: List[float]) -> Tuple[float, int]:
    """Per-sample sensor noise in metres, plus the run stride it was read at.

    Noise cannot be inferred from how the track was sampled, which is what
    issue #376 is about. Spacing says nothing about the source: a non-barometric
    phone, a Garmin on smart recording and a track simplified before upload are
    all sparse AND noisy, while a route planner's DEM export is sparse and
    clean. So measure it instead of guessing from geometry.

    The measurement is a median absolute k-th difference scaled back to a
    standard deviation. Differencing a series k times annihilates any local
    polynomial of degree below k, so terrain must bend more sharply than a
    degree-k polynomial to register at all, while independent noise — having no
    shape to annihilate — always survives at ``sigma * sqrt(C(2k, k))``.

    Two properties follow, and both were premises the previous estimator got
    wrong:

    * **Curvature.** Second differences (what it used) are near zero only on a
      STRAIGHT flank; they scale with the square of the spacing on any bend, so
      a clean curved route at 100 m spacing read as sigma 2 and earned a 5 m
      band that erased its rollers whole. Higher differences vanish on a bend
      too: clean sinusoidal rollers of 10 m over 600 m at 100 m spacing measure
      sigma 0.23 here, against 0.83 from second differences.
    * **Scale.** Whatever terrain still shows through shrinks with every added
      order — for anything longer than ~3.4 samples per cycle — while the noise
      estimate is unchanged by construction. So take the SMALLEST estimate over
      a run of orders: the one least contaminated by terrain. Orders 3 to 5;
      order 2 is the discredited one, and by order 6 the minimum of six noisy
      estimates starts biasing sigma low (a true 1.2 measured 1.08, enough to
      let 32 m of phantom climb back into held-altitude flat ground).

    Differences are taken at the run stride so repeated altitude readings are
    not differenced against themselves — see :func:`_run_stride`.

    Returns ``0.0`` for a series too short to have
    :data:`_NOISE_MIN_DIFFERENCES` third differences. The band then sits at its floor, which keeps the genuine
    steps in a handful of points — the tail of an edited piece — rather than
    dismissing them as jitter on the strength of two or three samples.
    """
    stride = _run_stride(elevations)
    differences = elevations
    estimate: Optional[float] = None
    for order in range(1, _NOISE_DIFFERENCE_ORDERS.stop):
        differences = [b - a for a, b
                       in zip(differences, islice(differences, stride, None))]
        if len(differences) < _NOISE_MIN_DIFFERENCES:
            break
        if order not in _NOISE_DIFFERENCE_ORDERS:
            continue
        step = 1 + len(differences) // _NOISE_MEDIAN_SAMPLE_CAP
        magnitudes = sorted(map(abs, differences[::step]))
        middle = magnitudes[len(magnitudes) // 2]
        sigma = _NOISE_DIFFERENCE_SCALE[order] * middle
        estimate = sigma if estimate is None else min(estimate, sigma)
    return (estimate if estimate is not None else 0.0), stride


def _smooth_elevations(
    elevations: List[float],
    distances_km: Optional[List[float]],
    sigma: float,
    stride: int,
) -> Tuple[List[float], float]:
    """Centred moving average over travel, widened to suit the measured noise.

    The span is measured in distance, not samples, so the same terrain recorded
    at 1 Hz and at one point per 100 m gets the same physical filtering. A fixed
    span is not enough on its own, though: :data:`ELEV_SMOOTH_SPAN_M` of a track
    sampled every 40 m holds one point and averages nothing, which is why the
    previous version skipped sparse series outright — on the theory that sparse
    meant route-planner DEM output with no noise in it. It does not. 30 km of
    flat ground at 40 m spacing under sigma 3 came back as 652 m of climb.

    So the span grows with the noise instead. Averaging m samples divides noise
    by sqrt(m) and we want :data:`ELEV_SMOOTH_TARGET_SIGMA_M` left, so the
    window must hold ``(sigma / target) ** 2`` readings — times the run stride,
    since repeated readings average to themselves and count for one. A clean
    series asks for none of this and keeps the 60 m floor, which is what leaves
    a sparse planned route untouched. Capped at
    :data:`ELEV_SMOOTH_MAX_SPAN_M`, beyond which the band takes over.

    The window is clamped at both ends rather than padded, so the first and last
    samples average over whatever neighbours exist. Endpoints therefore keep
    slightly more of their own noise than the middle does — immaterial for a
    gain figure accumulated over the whole track.

    Returns the smoothed series and the mean number of samples its windows
    held, which is how :func:`_noise_threshold` knows what noise is left. The
    mean, not the median, purely because it needs no second pass over 200k
    window widths — the two differ only by the half-width windows at the ends.
    Without ``distances_km`` (a caller that has elevations only) the series is
    returned untouched with a window of 1: a guessed span is worse than none,
    and the band then sizes itself from the full noise.
    """
    n = len(elevations)
    if n < 3 or not distances_km or len(distances_km) != n:
        return list(elevations), 1.0

    gaps = sorted([b - a for a, b
                   in zip(distances_km, islice(distances_km, 1, None))])
    median_gap_m = gaps[len(gaps) // 2] * 1000.0
    wanted = stride * (sigma / ELEV_SMOOTH_TARGET_SIGMA_M) ** 2 * median_gap_m
    span = max(ELEV_SMOOTH_SPAN_M, min(ELEV_SMOOTH_MAX_SPAN_M, wanted))
    half_km = (span / 2.0) / 1000.0

    # Prefix sums so each window costs one subtraction rather than re-adding its
    # members: the window holds ~11 samples of a 1 Hz ride but ~60 of a track
    # recorded every metre, and re-summing made the whole pass O(n * window).
    prefix: List[float] = [0.0]
    for value in elevations:
        prefix.append(prefix[-1] + value)

    out: List[float] = []
    total_width = 0
    lo = hi = 0
    for i in range(n):
        while distances_km[i] - distances_km[lo] > half_km:
            lo += 1
        while hi + 1 < n and distances_km[hi + 1] - distances_km[i] <= half_km:
            hi += 1
        width = hi + 1 - lo
        total_width += width
        out.append((prefix[hi + 1] - prefix[lo]) / width)
    return out, total_width / n


def _noise_threshold(sigma: float, stride: int, window: float) -> float:
    """Hysteresis band, sized from the noise smoothing did NOT remove.

    ``window`` samples averaged is ``window / stride`` independent readings
    averaged, which leaves ``sigma / sqrt(window / stride)``. Sizing the band
    from the raw sigma instead charges twice for noise already filtered out, and
    the band is paid for in real terrain: it costs roughly its own height per
    roller.

    Clamped: never below :data:`ELEV_GAIN_THRESHOLD_MIN_M`, so a perfectly clean
    series still ignores floating-point dust, and never above
    :data:`ELEV_GAIN_THRESHOLD_MAX_M`, so a catastrophically noisy one cannot
    raise the band until real mountains fit inside it. That ceiling is only
    reached past ~5 m of residual noise, by which point no hill it could swallow
    was resolvable anyway.
    """
    residual = sigma / math.sqrt(max(1.0, window / stride))
    return min(ELEV_GAIN_THRESHOLD_MAX_M,
               max(ELEV_GAIN_THRESHOLD_MIN_M,
                   ELEV_NOISE_SIGMA_MULTIPLE * residual))


def elevation_gain(
    elevations: List[float], distances_km: Optional[List[float]] = None
) -> float:
    """Total ascent in metres over an ordered elevation series.

    Summing every positive sample-to-sample delta — which is what this did until
    issue #260 — counts sensor noise as climbing. Every upward flicker is added
    and no downward one subtracts it, so the error accumulates in one direction
    and grows with the sample count. On a 6000-sample track with a true 600 m
    climb and ±1.2 m of ordinary GPS/barometric noise it reported 4094 m.

    So: measure the noise (:func:`_noise_estimate`), smooth over enough distance
    to bring it down (:func:`_smooth_elevations`), then accumulate through a
    hysteresis band sized from whatever is left (:func:`_noise_threshold`).
    ``ref`` is the last elevation counted; a rise is booked only once the series
    climbs a band above it, and ``ref`` only follows the series down once it
    falls a band below. Movement inside the band is drift. That fixture then
    reports 599.2 m.

    All three steps hang off one measurement, and that is what issue #376 fixed:
    the previous version inferred noise from sampling geometry instead, skipping
    smoothing on any sparse series and reading its band off second differences.
    Both premises were false. Spacing does not identify the source — a
    non-barometric phone is sparse AND noisy, and 30 km of flat ground at 40 m
    spacing with sigma 3 read 652 m of climb, now 0. And second differences are
    near zero only on straight flanks, not on bends — clean sinusoidal rollers
    of 10 m over 600 m at 100 m spacing read 0 of their true 500, now 500.

    ``distances_km`` is the cumulative distance of each sample, and is what
    makes the window physical rather than a function of the recording rate.

    Strava-synced activities never reach here — their ``total_elevation_gain``
    arrives already processed. This is the figure for tracks we derive
    ourselves: hand-edited pieces, splits, and GPX imports.
    """
    if len(elevations) < 2:
        return 0.0
    sigma, stride = _noise_estimate(elevations)
    smoothed, window = _smooth_elevations(
        elevations, distances_km, sigma, stride)
    threshold = _noise_threshold(sigma, stride, window)
    gain = 0.0
    ref = smoothed[0]
    for value in smoothed[1:]:
        if value - ref >= threshold:
            gain += value - ref
            ref = value
        elif ref - value >= threshold:
            ref = value
    return gain


# ── Terrain-model gain: the flatness oracle (issue #386) ──────────────────────
#
# Everything above works on one series of elevations over distance, and that is
# why the phantom climb on a phone recording cannot be removed there. Correlated
# sensor drift and gentle terrain have the SAME SPECTRUM on the distance axis:
# they are not separable, which was established by sweeping every span x
# threshold pair, and by PR #389 measuring the marginal sigma correctly and
# erasing up to 100% of a real 1000 m day for it. The time axis does not rescue
# it either — at roughly constant speed time and distance are one axis up to a
# scale factor.
#
# So this does not try. It brings in a SECOND, INDEPENDENT measurement — the
# elevation a terrain model reports along the same path — and uses it for the one
# question it can answer without ambiguity: *is there any relief here at all?*
#
# Where the terrain model says there is none, every metre the sensor reported is
# invented, and the terrain model's own steps replace it. Where the terrain model
# sees relief, the recording stands untouched: it is the better of the two there
# (within 14% on 200 m rollers, where a 30 m terrain model is 29% low), and
# leaving it alone is what makes this safe to ship.

#: Length of path over which the relief question is asked, in metres.
#:
#: Per-activity is too coarse — a walk half along a flat promenade and half up a
#: hill has to keep its hill, and one verdict for the whole track cannot do that
#: (measured: 452 m reported against a true 300; windowed, 309).
TERRAIN_WINDOW_M = 500.0

#: How much relief a window must show before the recording is trusted, in metres.
#:
#: Measured per 500 m window: flat ground reads 0.00, a smoothed path wandering
#: across a 20% slope reads 0.74-3.62 (pure artefact), a shallow river valley
#: 1.84-2.06, a 1.5% urban drag 6.88-7.71, and 10 m rollers 8.95-9.98.
#:
#: The valley and the cross-slope artefact OVERLAP, so no threshold separates
#: them. 5 m puts both on the flat side, which is right for the artefact and, as
#: it happens, near-right for the valley too (38.6 m reported against a true 40)
#: because a terrain model is accurate on relief that shallow. Dropping to 2 m to
#: "save" the valley instead lets 115 m of cross-slope artefact back in.
TERRAIN_RELIEF_M = 5.0


def terrain_corrected_gain(
    recorded: List[float],
    terrain: List[float],
    distances_km: Optional[List[float]] = None,
    *,
    window_m: float = TERRAIN_WINDOW_M,
    relief_m: float = TERRAIN_RELIEF_M,
) -> float:
    """Ascent over a recording, with flat stretches taken from the terrain model.

    ``terrain`` is the terrain-model elevation at each of ``recorded``'s points,
    sampled along a path already smoothed in plan view — smoothing the PATH is
    legitimate in a way smoothing the elevation is not, because a road's plan
    geometry is smooth at a scale far above GPS horizontal error. The two lists
    must be the same length; ``distances_km`` is as :func:`elevation_gain` takes
    it.

    Falls back to :func:`elevation_gain` on the recording alone when no terrain
    is available, which is a normal state and not an error: the tile source has
    no SLA, and an end-to-end encrypted activity's geometry cannot be read by
    the server at all.

    **Why the windows splice deltas rather than sum their own gains.** Summing a
    per-window :func:`elevation_gain` resets the hysteresis reference and
    re-smooths the series at every boundary, which read 766 m where the recording
    reads 858 m on 200 m rollers — a 92 m loss on exactly the case this is meant
    to leave alone. Composing the steps into one series and accumulating ONCE
    makes the all-relief case bit-identical to the recording, which is the
    property that makes this safe. Splicing steps rather than elevations also
    disposes of the offset between the two sources for free: barometric drift
    puts them at different levels, and only their steps are ever used.
    """
    if not terrain or len(terrain) != len(recorded):
        return elevation_gain(recorded, distances_km)
    if len(recorded) < 3:
        return elevation_gain(recorded, distances_km)

    per = _terrain_window_samples(distances_km, len(recorded), window_m)
    series = [recorded[0]]
    for lo in range(0, len(recorded) - 1, per):
        # One sample PAST the window's own end, so consecutive windows share a
        # boundary sample and every step in the track is contributed exactly
        # once. Slicing ``[lo:lo + per]`` instead drops the step across each
        # boundary — 39 of them on a 20 km track at this window size, which is
        # enough on its own to stop the all-relief case being the exact no-op
        # the paragraph above claims.
        hi = min(len(recorded), lo + per + 1)
        window = terrain[lo:hi]
        flat = len(window) >= 3 and (max(window) - min(window)) < relief_m
        source = window if flat else recorded[lo:hi]
        for previous, current in zip(source, source[1:]):
            series.append(series[-1] + (current - previous))

    return elevation_gain(series, distances_km)


def _terrain_window_samples(
    distances_km: Optional[List[float]], count: int, window_m: float
) -> int:
    """How many samples span *window_m* of travel, at least 3.

    Derived from the distance axis where there is one, so a 1 Hz walk and a
    sparse planned route ask the relief question over the same length of ground
    rather than the same number of points — the mistake that erased planned
    routes in #376.
    """
    if distances_km and len(distances_km) >= 2:
        travelled_m = (distances_km[-1] - distances_km[0]) * 1000.0
        if travelled_m > 0:
            spacing_m = travelled_m / max(1, count - 1)
            return max(3, int(round(window_m / spacing_m)))
    return max(3, count // 2)


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
