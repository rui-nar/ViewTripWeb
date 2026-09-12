"""Two-dimensional fixtures: a terrain surface, a track over it, a model of it.

The 1-D generators in :mod:`generators` produce an elevation series over
distance, which is all the estimator ever sees. The flatness oracle needs more
than that: a surface, a path across it that wanders horizontally as a real GPS
trace does, and a *model* of that surface with the resolution a real terrain
tileset has.

Three things here are deliberate, and the numbers in ``cases.py`` mean nothing
without them:

**The model is a grid, not the surface.** :func:`terrain_model` samples the
surface on 30 m posts and reads it back bilinearly, which is what a
Copernicus/SRTM-class tileset gives. Reading the analytic surface instead would
measure an ideal nothing can reach, and raising the tile zoom does not help
either: it interpolates the same posts.

Be careful attributing the loss, though. The 30 m grid keeps 97% of a 10 m/200 m
roller field and 83% of a 10 m/100 m one as a raw ascent; it is
:func:`src.models.track_edit.elevation_gain`'s own 60 m smoothing floor that
takes those to 70% and 30% — and it takes the PERFECT surface to 80% and 43%.
The grid is the smaller term by 3.4x at 100 m wavelength. So ``model_ceiling`` is
mostly a limit of the gain pipeline rather than of the data, and "a 30 m model
cannot see a short hill" is a third of the story at best.

**The noise is horizontal as well as vertical.** Sampling a terrain model
removes vertical sensor error completely, and then converts *horizontal* error
into vertical error through the terrain gradient — on a 20% slope, 10 m sideways
is 2 m up. A fixture with no horizontal noise would make the approach look
perfect and hide its one real cost.

**The path is smoothed before the model is read.** This is not a refinement, it
is the step that makes the whole approach work: a road's plan geometry is smooth
at a scale (tens of metres of curvature radius) far above GPS horizontal error,
so averaging the path is legitimate where averaging the elevation is not.
"""
from __future__ import annotations

import math
import random
from typing import Callable, Iterable, List, NamedTuple, Sequence, Tuple

from src.models.track_edit import elevation_gain

from .generators import _ar1

#: Grid spacing of the modelled terrain, in metres. Copernicus GLO-30 and the
#: SRTM-derived terrarium tiles are both ~30 m; nothing global is finer.
MODEL_POST_M = 30.0

#: Plan-view smoothing applied to the path before the model is read.
PATH_SMOOTH_M = 100.0

Surface = Callable[[float, float], float]


class TerrainTrack(NamedTuple):
    """One track over a surface, as the oracle will actually meet it."""

    #: What the sensor recorded: true elevation plus correlated vertical error.
    recorded: List[float]
    #: The model's elevation at each point of the smoothed path.
    terrain: List[float]
    #: Cumulative distance in km, one per sample.
    distances_km: List[float]
    #: Ascent of the true surface along the true path — the honest target.
    true_gain: float
    #: What the gain pipeline reports from the model along the TRUE path, with
    #: no sensor error at all — the ceiling this approach can reach, which is
    #: NOT ``true_gain``. Through :func:`elevation_gain`, not a raw positive
    #: sum: the 60 m smoothing floor erodes fine terrain further than the grid
    #: alone does (a 10 m/200 m roller field: 999 true, 967 off the raw grid,
    #: 704 through the pipeline), and quoting the raw figure would let that loss
    #: hide inside the baseline.
    #:
    #: It is NOT what pure substitution would report in production, and that
    #: difference is the point of this fixture: substitution samples along the
    #: noisy smoothed path, not the true one, so on a 20% cross-slope it reports
    #: 28.5 m where this ceiling is 0.0 — the coupling term, which no true-path
    #: figure can show. The two agree within a few metres wherever the terrain
    #: has no cross-track gradient.
    model_ceiling: float


# ── Surfaces ─────────────────────────────────────────────────────────────────
def flat_plain() -> Surface:
    """Level ground. Every metre reported is invented."""
    return lambda x, y: 100.0


def cross_slope(grade: float = 0.20) -> Surface:
    """Level along travel, steep across it.

    Nothing is climbed, so anything reported is the horizontal-into-vertical
    coupling term on its own — the cost this approach adds rather than removes.
    """
    return lambda x, y: 100.0 + grade * y


def rollers(wavelength_m: float, amplitude_m: float = 5.0) -> Surface:
    """Sinusoidal hills. Sinusoidal matters: triangular flanks have zero
    curvature and hid two broken estimators (see ``cases.py``)."""
    return lambda x, y: 100.0 + amplitude_m * math.sin(
        2 * math.pi * x / wavelength_m)


def steady_grade(grade: float = 0.015) -> Surface:
    """A continuous drag. Real climb, modest relief in any one window — the
    case an over-eager oracle would erase."""
    return lambda x, y: 100.0 + grade * x


def shallow_valley(depth_m: float = 40.0, length_m: float = 20_000.0) -> Surface:
    """Down and back up, gently: 0.4% grades. Its relief per window overlaps
    the cross-slope artefact's, which is why the threshold sits where it does."""

    def surface(x: float, y: float) -> float:
        return 100.0 - depth_m * (1 - abs(2 * (x / length_m) - 1))

    return surface


def half_flat_half_hill(height_m: float = 300.0,
                        length_m: float = 20_000.0) -> Surface:
    """Level for the first half, a hill in the second.

    The case that decides windowed against per-activity: one verdict for the
    whole track has to get this wrong in one direction or the other.
    """

    def surface(x: float, y: float) -> float:
        if x <= length_m / 2:
            return 100.0
        t = (x - length_m / 2) / (length_m / 2)
        return 100.0 + height_m * (1 - abs(2 * t - 1))

    return surface


def valley_with_viaduct(depth_m: float = 60.0, half_span_m: float = 150.0,
                        length_m: float = 20_000.0) -> Surface:
    """A gorge crossed on the level by a bridge the model knows nothing about.

    A bare-earth model reads the rider as being on the gorge floor, inventing a
    descent and a climb that never happened. The failure mode to keep measured.
    """

    def surface(x: float, y: float) -> float:
        d = abs(x - length_m / 2)
        if d >= half_span_m:
            return 100.0
        return 100.0 - depth_m * (1 - (d / half_span_m) ** 2)

    return surface


# ── The model ────────────────────────────────────────────────────────────────
def terrain_model(surface: Surface, post_m: float = MODEL_POST_M,
                  post_sigma_m: float = 0.0, seed: int = 101,
                  error_length_m: float = 0.0) -> Surface:
    """*surface* as a terrain tileset would report it: gridded, read bilinearly.

    ``post_sigma_m`` gives each post its own independent error, which a real
    tileset has and a perfectly smooth analytic grid does not. Copernicus
    GLO-30's relative accuracy is about 2 m LE90 (sigma ~1.2) and an
    SRTM-derived mosaic is worse, so zero is the optimistic case rather than
    the realistic one — and a benchmark whose model is noise-free cannot see a
    relief statistic that flips on one bad post.

    ``error_length_m`` is the distance over which that error stays correlated,
    and it matters more than its size. Zero makes every post independent, which
    is the pessimistic bound and almost certainly the WRONG model: a DEM built
    from interferometric SAR or stereo imagery has error that varies over
    hundreds of metres, so adjacent posts share most of theirs. The two models
    behave completely differently — independent post error produces apparent
    relief within a 500 m window out of nothing, while correlated error mostly
    cancels in a range. The same white-versus-AR(1) distinction decides this
    whole issue on the vertical axis, and getting it wrong here would mean
    tuning a statistic against a fiction.

    The error is a deterministic function of position rather than a sequence, so
    the same post reads the same value however the track crosses it — otherwise
    a smoothed path re-reading a post would average its error away and the
    fixture would understate the problem.
    """

    def _draw(ix: int, iy: int) -> float:
        h = hash((ix, iy, seed)) & 0xFFFFFFFF
        # Two uniforms -> one normal (Box-Muller), so the tail is right.
        u1 = ((h & 0xFFFF) + 0.5) / 65536.0
        u2 = (((h >> 16) & 0xFFFF) + 0.5) / 65536.0
        return math.sqrt(-2.0 * math.log(u1)) * math.cos(2 * math.pi * u2)

    def post_error(ix: int, iy: int) -> float:
        if post_sigma_m <= 0.0:
            return 0.0
        if error_length_m <= post_m:
            return post_sigma_m * _draw(ix, iy)
        # Independent draws on a coarse grid of ``error_length_m``, read back
        # bilinearly: an error field that varies over that distance instead of
        # per post.
        cells = error_length_m / post_m
        gx, gy = ix / cells, iy / cells
        cx, cy = math.floor(gx), math.floor(gy)
        fx, fy = gx - cx, gy - cy
        return post_sigma_m * (
            _draw(cx, cy) * (1 - fx) * (1 - fy)
            + _draw(cx + 1, cy) * fx * (1 - fy)
            + _draw(cx, cy + 1) * (1 - fx) * fy
            + _draw(cx + 1, cy + 1) * fx * fy)

    def read(x: float, y: float) -> float:
        gx, gy = x / post_m, y / post_m
        x0, y0 = math.floor(gx), math.floor(gy)
        fx, fy = gx - x0, gy - y0
        z00 = surface(x0 * post_m, y0 * post_m) + post_error(x0, y0)
        z10 = surface((x0 + 1) * post_m, y0 * post_m) + post_error(x0 + 1, y0)
        z01 = surface(x0 * post_m, (y0 + 1) * post_m) + post_error(x0, y0 + 1)
        z11 = (surface((x0 + 1) * post_m, (y0 + 1) * post_m)
               + post_error(x0 + 1, y0 + 1))
        return (z00 * (1 - fx) * (1 - fy) + z10 * fx * (1 - fy)
                + z01 * (1 - fx) * fy + z11 * fx * fy)

    return read


def smooth_path(xs: List[float], ys: List[float], span_m: float,
                spacing_m: float) -> Tuple[List[float], List[float]]:
    """Average the path in plan view over *span_m* of travel."""
    half = max(1, int(round(span_m / spacing_m / 2)))
    out_x: List[float] = []
    out_y: List[float] = []
    for i in range(len(xs)):
        lo, hi = max(0, i - half), min(len(xs), i + half + 1)
        out_x.append(sum(xs[lo:hi]) / (hi - lo))
        out_y.append(sum(ys[lo:hi]) / (hi - lo))
    return out_x, out_y


def positive_sum(series: List[float]) -> float:
    """Ascent of a NOISE-FREE series — a plain sum of its positive steps."""
    return sum(max(0.0, b - a) for a, b in zip(series, series[1:]))


# ── Assembly ─────────────────────────────────────────────────────────────────
def track_over(
    surface: Surface,
    length_km: float = 20.0,
    spacing_m: float = 5.0,
    speed_ms: float = 5.0,
    sigma_v: float = 3.0,
    sigma_h: float = 5.0,
    tau_s: float = 20.0,
    seed: int = 17,
    path_smooth_m: float = PATH_SMOOTH_M,
    on_the_level: bool = False,
    vertical_kind: str = "ar1",
    post_sigma_m: float = 0.0,
    error_length_m: float = 0.0,
) -> TerrainTrack:
    """Walk east across *surface*, recording badly.

    ``sigma_v`` is the marginal deviation of the vertical error and ``sigma_h``
    of the horizontal, both AR(1) over ``tau_s`` seconds — the standard
    first-order model for sensor drift, and the reason this error is not
    separable from terrain on the distance axis.

    ``on_the_level`` records the rider as staying at a constant elevation
    whatever the surface does underneath, which is what crossing a bridge looks
    like to the sensor.

    ``vertical_kind`` picks the vertical error's shape. ``"ar1"`` is the phone's
    correlated drift; ``"white"`` is the uncorrelated error a sparse recording
    carries, and it matters because the gain pipeline's smoothing span and
    hysteresis band both come off a noise measurement — a sparse white-noise
    track is the one place they are NOT already pinned at their floors, so it is
    the only fixture that can see a change in what that measurement reads.

    ``post_sigma_m`` and ``error_length_m`` are passed to
    :func:`terrain_model`.
    """
    count = max(3, int(length_km * 1000 / spacing_m))
    xs_true = [i * spacing_m for i in range(count)]
    ys_true = [0.0] * count
    distances_km = [i * spacing_m / 1000.0 for i in range(count)]
    tau_samples = tau_s * speed_ms / spacing_m

    z_true = ([100.0] * count if on_the_level
              else [surface(x, y) for x, y in zip(xs_true, ys_true)])

    if vertical_kind == "white":
        rng = random.Random(seed)
        vertical = [rng.gauss(0.0, sigma_v) for _ in range(count)]
    else:
        vertical = _ar1(count, sigma_v, tau_samples, seed)
    east = _ar1(count, sigma_h, tau_samples, seed + 1)
    north = _ar1(count, sigma_h, tau_samples, seed + 2)

    recorded = [z + e for z, e in zip(z_true, vertical)]
    xs_noisy = [x + d for x, d in zip(xs_true, east)]
    ys_noisy = [y + d for y, d in zip(ys_true, north)]
    xs_path, ys_path = smooth_path(xs_noisy, ys_noisy, path_smooth_m, spacing_m)

    model = terrain_model(surface, post_sigma_m=post_sigma_m, seed=seed + 7,
                          error_length_m=error_length_m)
    terrain = [model(x, y) for x, y in zip(xs_path, ys_path)]
    ceiling_series = [model(x, y) for x, y in zip(xs_true, ys_true)]

    return TerrainTrack(
        recorded=recorded,
        terrain=terrain,
        distances_km=distances_km,
        true_gain=positive_sum(z_true),
        model_ceiling=elevation_gain(ceiling_series, distances_km),
    )


def track_over_segments(
    surface: Surface,
    segments: Sequence[Tuple[float, float, float]],
    sigma_v: float = 3.0,
    sigma_h: float = 5.0,
    tau_s: float = 20.0,
    seed: int = 17,
    path_smooth_m: float = PATH_SMOOTH_M,
    post_sigma_m: float = 0.0,
) -> TerrainTrack:
    """One recording whose sample spacing changes along the track.

    ``segments`` is ``(length_km, spacing_m, speed_ms)`` in order — one 1 Hz
    device carried at different speeds, which is an ordinary walk-then-ride or
    ride-then-stop, not a contrived input.

    This exists because a window derived from the track's MEAN spacing means
    different lengths of ground in different places: 5 km on foot at 1.4 m/s
    then 15 km riding at 8 m/s has a mean of 5.4 m, so a fixed sample count asks
    the relief question over 190 m in the walk and 1088 m in the ride. Every
    other fixture here is uniformly spaced and cannot see that.
    """
    xs_true: List[float] = []
    for length_km, spacing_m, _speed in segments:
        start = xs_true[-1] + spacing_m if xs_true else 0.0
        steps = max(2, int(length_km * 1000 / spacing_m))
        xs_true.extend(start + i * spacing_m for i in range(steps))
    count = len(xs_true)
    ys_true = [0.0] * count

    # tau in samples changes with the segment, so build the noise per segment
    # at the rate that segment was recorded at.
    vertical: List[float] = []
    east: List[float] = []
    north: List[float] = []
    offset = 0
    for index, (length_km, spacing_m, speed_ms) in enumerate(segments):
        steps = max(2, int(length_km * 1000 / spacing_m))
        tau_samples = tau_s * speed_ms / spacing_m
        vertical.extend(_ar1(steps, sigma_v, tau_samples, seed + offset))
        east.extend(_ar1(steps, sigma_h, tau_samples, seed + offset + 1))
        north.extend(_ar1(steps, sigma_h, tau_samples, seed + offset + 2))
        offset += 3 + index
    vertical, east, north = vertical[:count], east[:count], north[:count]

    z_true = [surface(x, y) for x, y in zip(xs_true, ys_true)]
    recorded = [z + e for z, e in zip(z_true, vertical)]
    distances_km = [x / 1000.0 for x in xs_true]

    xs_noisy = [x + d for x, d in zip(xs_true, east)]
    ys_noisy = [y + d for y, d in zip(ys_true, north)]
    xs_path, ys_path = _smooth_path_by_distance(
        xs_noisy, ys_noisy, xs_true, path_smooth_m)

    model = terrain_model(surface, post_sigma_m=post_sigma_m, seed=seed + 7)
    terrain = [model(x, y) for x, y in zip(xs_path, ys_path)]
    ceiling = [model(x, y) for x, y in zip(xs_true, ys_true)]

    return TerrainTrack(
        recorded=recorded,
        terrain=terrain,
        distances_km=distances_km,
        true_gain=positive_sum(z_true),
        model_ceiling=elevation_gain(ceiling, distances_km),
    )


def _smooth_path_by_distance(
    xs: List[float], ys: List[float], along_m: List[float], span_m: float,
) -> Tuple[List[float], List[float]]:
    """Plan-view smoothing over a span of GROUND rather than a sample count.

    :func:`smooth_path` counts samples, which is correct only while spacing is
    uniform. Averaging a fixed number of samples on a track that changes rate
    smooths 1.4 m of walking and 8 m of riding over different distances, and the
    coupling term this smoothing exists to suppress scales with distance.
    """
    out_x: List[float] = []
    out_y: List[float] = []
    half = span_m / 2.0
    lo = 0
    hi = 0
    for i in range(len(xs)):
        while along_m[i] - along_m[lo] > half:
            lo += 1
        while hi + 1 < len(xs) and along_m[hi + 1] - along_m[i] <= half:
            hi += 1
        span = max(1, hi - lo + 1)
        out_x.append(sum(xs[lo:hi + 1]) / span)
        out_y.append(sum(ys[lo:hi + 1]) / span)
    return out_x, out_y
