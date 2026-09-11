"""Synthetic track generators for the elevation-gain benchmark (issue #386).

Each generator returns ``(elevations_m, distances_km, true_gain_m)`` — the input
:func:`src.models.track_edit.elevation_gain` takes, plus the answer a perfect
estimator would give.

The point of naming them by RECORDING CLASS rather than by shape is that the
elevation figure's accuracy is decided by which sensor produced the series, not
by the terrain under it. Four rounds of fixes on this function each failed the
same way — a change measured against one class, shipped, and found to have
wrecked another — so the classes are enumerated here once:

``clean``
    No sensor at all. A route drawn in a planner and sampled from a terrain
    model: Komoot, RideWithGPS, a Garmin course. Smooth, sparse, exact.
``barometric``
    A watch or head unit with a pressure sensor. Small white noise plus a slow
    drift as the weather moves. This is the good case.
``phone``
    GPS altitude with no barometer. Error is large AND autocorrelated — it
    wanders over minutes rather than flickering per sample, which is what makes
    it indistinguishable from gentle terrain. This is the hard case, and the
    one issue #386 is about.
``smart``
    A device recording a point every so often rather than every second, or a
    track simplified before upload. Sparse and noisy at once.
"""
from __future__ import annotations

import math
import random
from typing import List, Tuple

Track = Tuple[List[float], List[float], float]

#: Marginal deviation and correlation time (seconds) of phone-class GPS
#: altitude error. Correlation over minutes is the Gauss-Markov convention used
#: for GPS vertical error; the deviation is the pessimistic end of what a
#: handset produces without a barometer.
#:
#: The correlation time is the least certain number in this file — it is a
#: convention, not a measurement from real handsets, and how long the error
#: stays correlated decides how much of it survives smoothing. So the benchmark
#: sweeps ``tau_s`` rather than trusting one value: a change that looks safe at
#: one correlation time can erase terrain at another, which is precisely how
#: PR #389 passed its author's fixtures and failed review.
PHONE_SIGMA_M = 4.0
PHONE_TAU_S = 60.0

#: Barometric noise: a small per-sample component plus a slow weather drift.
BARO_SIGMA_M = 0.3
BARO_DRIFT_M = 1.0
BARO_DRIFT_TAU_S = 300.0


def _ar1(count: int, sigma: float, tau_samples: float, seed: int) -> List[float]:
    """Autocorrelated noise: marginal deviation *sigma*, correlation *tau*.

    ``tau_samples`` is in SAMPLES, so a caller converts from seconds using the
    recording rate. An AR(1) process is the standard first-order model for
    sensor drift, and is what makes this noise inseparable from terrain on the
    distance axis — it has the same spectrum as gentle hills.
    """
    random.seed(seed)
    if tau_samples <= 0:
        return [random.gauss(0, sigma) for _ in range(count)]
    phi = math.exp(-1.0 / tau_samples)
    innovation = sigma * math.sqrt(max(0.0, 1 - phi * phi))
    value = random.gauss(0, sigma)
    out = []
    for _ in range(count):
        value = phi * value + random.gauss(0, innovation)
        out.append(value)
    return out


def _noise(kind: str, count: int, spacing_m: float, speed_ms: float, seed: int,
           sigma: float = 3.0, tau_s: float = PHONE_TAU_S) -> List[float]:
    """Per-sample sensor error for one recording class.

    ``sigma`` applies to the ``white`` class only; the others carry the
    deviation their sensor actually has.
    """
    if kind == "clean":
        return [0.0] * count
    seconds_per_sample = spacing_m / speed_ms if speed_ms > 0 else 1.0
    if kind == "phone":
        return _ar1(count, PHONE_SIGMA_M, tau_s / seconds_per_sample, seed)
    if kind == "barometric":
        drift = _ar1(count, BARO_DRIFT_M, BARO_DRIFT_TAU_S / seconds_per_sample, seed)
        random.seed(seed + 1000)
        return [d + random.gauss(0, BARO_SIGMA_M) for d in drift]
    if kind == "white":
        random.seed(seed)
        return [random.gauss(0, sigma) for _ in range(count)]
    raise ValueError(f"unknown recording class: {kind}")


def _assemble(profile: List[float], kind: str, spacing_m: float,
              speed_ms: float, seed: int, true_gain: float,
              sigma: float = 3.0, tau_s: float = PHONE_TAU_S) -> Track:
    noise = _noise(kind, len(profile), spacing_m, speed_ms, seed, sigma, tau_s)
    elevations = [p + n for p, n in zip(profile, noise)]
    distances = [i * spacing_m / 1000.0 for i in range(len(profile))]
    return elevations, distances, true_gain


def flat(length_km: float, spacing_m: float, kind: str,
         speed_ms: float = 1.4, seed: int = 5, sigma: float = 3.0,
         tau_s: float = PHONE_TAU_S) -> Track:
    """Level ground. True gain is zero, so anything reported is phantom."""
    count = max(3, int(length_km * 1000 / spacing_m))
    return _assemble([100.0] * count, kind, spacing_m, speed_ms, seed, 0.0,
                     sigma, tau_s)


def climb(height_m: float, length_km: float, spacing_m: float, kind: str,
          speed_ms: float = 1.4, seed: int = 7) -> Track:
    """One climb up and back down — the shape a pass or a summit makes."""
    count = max(3, int(length_km * 1000 / spacing_m))
    profile = [200.0 + height_m * (1 - abs(2 * (i / (count - 1)) - 1))
               for i in range(count)]
    return _assemble(profile, kind, spacing_m, speed_ms, seed, height_m)


def rollers(height_m: float, wavelength_m: float, length_km: float,
            spacing_m: float, kind: str, speed_ms: float = 5.0,
            seed: int = 3, shape: str = "sine", sigma: float = 3.0,
            tau_s: float = PHONE_TAU_S) -> Track:
    """Repeating hills — the case every previous round erased.

    Sinusoidal by default. Triangular hills have straight flanks and therefore
    zero curvature, which is exactly the blind spot that let a broken estimator
    look healthy for two rounds; ``shape="tri"`` is kept only to pin that.
    """
    per = max(2, round(wavelength_m / spacing_m))
    count = max(3, int(length_km * 1000 / spacing_m))
    profile = []
    for i in range(count):
        phase = i % per
        if shape == "sine":
            rise = height_m / 2 * (1 - math.cos(2 * math.pi * phase / per))
        else:
            half = per / 2
            rise = height_m * (phase / half if phase < half else (per - phase) / half)
        profile.append(300.0 + rise)
    return _assemble(profile, kind, spacing_m, speed_ms, seed,
                     height_m * (count // per), sigma, tau_s)


def held_readings(length_km: float, spacing_m: float, hold: int,
                  kind: str = "phone", speed_ms: float = 1.4, seed: int = 11) -> Track:
    """Flat ground where the altimeter updates slower than the GPS fix.

    The same reading repeats for *hold* samples, which collapses a naive noise
    estimate to zero and lets every step between updates count as a climb.
    """
    elevations, distances, _ = flat(length_km, spacing_m, kind, speed_ms, seed)
    held = [elevations[(i // hold) * hold] for i in range(len(elevations))]
    return held, distances, 0.0


def true_gain_of(profile: List[float]) -> float:
    """Ascent of a NOISE-FREE profile — a plain sum of its positive steps.

    Exact only because there is no noise to accumulate, which is the whole
    reason the raw sum had to be abandoned for real series (issue #260).
    """
    return sum(max(0.0, b - a) for a, b in zip(profile, profile[1:]))


def fragment(noisy: Track, clean: Track,
             start_fraction: float, end_fraction: float) -> Track:
    """A slice of a track, as a split or a trimmed edit produces.

    Its true gain is the ascent actually inside the slice, taken from the
    noise-free twin — not a share of the parent's. That distinction is the
    property the apportioning work has to get right: a share is a good estimate
    of this number, and today's code recomputes an absolute figure instead.
    """
    noisy_e, distances, _ = noisy
    clean_e, _, _ = clean
    lo = int(len(noisy_e) * start_fraction)
    hi = max(lo + 3, int(len(noisy_e) * end_fraction))
    piece_d = [d - distances[lo] for d in distances[lo:hi]]
    return noisy_e[lo:hi], piece_d, true_gain_of(clean_e[lo:hi])
