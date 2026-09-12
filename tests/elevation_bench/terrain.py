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
measure an ideal nothing can reach, and would hide the model's own smoothing
inside every baseline — a 30 m model sees 70% of a 10 m/200 m roller and 30% of
a 10 m/100 m one. Raising the tile zoom does not help: it interpolates the same
posts.

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
from typing import Callable, List, NamedTuple, Tuple

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
    #: 704 through the pipeline), and quoting the raw figure would let that
    #: loss hide inside the baseline.
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
def terrain_model(surface: Surface, post_m: float = MODEL_POST_M) -> Surface:
    """*surface* as a terrain tileset would report it: gridded, read bilinearly."""

    def read(x: float, y: float) -> float:
        gx, gy = x / post_m, y / post_m
        x0, y0 = math.floor(gx), math.floor(gy)
        fx, fy = gx - x0, gy - y0
        z00 = surface(x0 * post_m, y0 * post_m)
        z10 = surface((x0 + 1) * post_m, y0 * post_m)
        z01 = surface(x0 * post_m, (y0 + 1) * post_m)
        z11 = surface((x0 + 1) * post_m, (y0 + 1) * post_m)
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
) -> TerrainTrack:
    """Walk east across *surface*, recording badly.

    ``sigma_v`` is the marginal deviation of the vertical error and ``sigma_h``
    of the horizontal, both AR(1) over ``tau_s`` seconds — the standard
    first-order model for sensor drift, and the reason this error is not
    separable from terrain on the distance axis.

    ``on_the_level`` records the rider as staying at a constant elevation
    whatever the surface does underneath, which is what crossing a bridge looks
    like to the sensor.
    """
    count = max(3, int(length_km * 1000 / spacing_m))
    xs_true = [i * spacing_m for i in range(count)]
    ys_true = [0.0] * count
    distances_km = [i * spacing_m / 1000.0 for i in range(count)]
    tau_samples = tau_s * speed_ms / spacing_m

    z_true = ([100.0] * count if on_the_level
              else [surface(x, y) for x, y in zip(xs_true, ys_true)])

    vertical = _ar1(count, sigma_v, tau_samples, seed)
    east = _ar1(count, sigma_h, tau_samples, seed + 1)
    north = _ar1(count, sigma_h, tau_samples, seed + 2)

    recorded = [z + e for z, e in zip(z_true, vertical)]
    xs_noisy = [x + d for x, d in zip(xs_true, east)]
    ys_noisy = [y + d for y, d in zip(ys_true, north)]
    xs_path, ys_path = smooth_path(xs_noisy, ys_noisy, path_smooth_m, spacing_m)

    model = terrain_model(surface)
    terrain = [model(x, y) for x, y in zip(xs_path, ys_path)]
    ceiling_series = [model(x, y) for x, y in zip(xs_true, ys_true)]

    return TerrainTrack(
        recorded=recorded,
        terrain=terrain,
        distances_km=distances_km,
        true_gain=positive_sum(z_true),
        model_ceiling=elevation_gain(ceiling_series, distances_km),
    )
