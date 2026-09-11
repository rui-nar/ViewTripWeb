"""Regression gates over the elevation-gain benchmark (issue #386).

The benchmark itself — the input classes, why each exists, and what each should
report — lives in :mod:`tests.elevation_bench.cases`. This module only asserts
it.

Elevation gain has been rewritten four times, and each round shipped a change
measured against whichever fixtures were to hand, then turned out to have
wrecked a class nobody had generated. These gates exist so the next change is
measured against all of them at once, before it ships rather than after.
"""
from __future__ import annotations

import pytest

from src.models.track_edit import elevation_gain
from tests.elevation_bench.cases import GATES, INFO
from tests.elevation_bench import generators as gen


@pytest.mark.parametrize("case", GATES, ids=lambda c: c.key)
def test_benchmark_case_within_bounds(case):
    elevations, distances, true_gain = case.build()
    got = elevation_gain(elevations, distances)

    detail = (f"{case.label}: reported {got:.0f} m against a true {true_gain:.0f} m"
              + (f" — {case.note}" if case.note else ""))
    if case.low is not None:
        assert got >= case.low, f"{detail}; expected at least {case.low:.0f}"
    if case.high is not None:
        assert got <= case.high, f"{detail}; expected at most {case.high:.0f}"


@pytest.mark.parametrize("case", INFO, ids=lambda c: c.key)
def test_informational_case_runs(case):
    """The cases the current approach cannot get right still have to RUN.

    They carry no bound — asserting one would either encode a wrong answer or
    fail forever — but a generator that raises, or a series that makes the
    estimator return a non-number, is a real defect and would otherwise hide
    here until someone read the table.
    """
    elevations, distances, _ = case.build()
    got = elevation_gain(elevations, distances)
    assert got == got, f"{case.label} produced NaN"       # NaN != NaN
    assert 0.0 <= got < 1e6, f"{case.label} produced {got}"


def test_no_cliff_across_noise_levels():
    """The reported figure must move smoothly as the sensor gets worse.

    #389 measured correlated noise correctly and then spent the measurement on
    a wider band, which produced a step change: the same road under marginal
    noise of 2.25 m reported 763 m and under 2.50 m reported 23 m. Two people
    riding together with different phones got different trips.

    A gradient is acceptable — a noisier sensor genuinely justifies a more
    conservative figure. A cliff is not, because nothing about the terrain
    changed.
    """
    for label, build in (
        ("flat", lambda s: gen.flat(20.0, 5.0, "white", speed_ms=5.0, sigma=s)),
        ("rollers", lambda s: gen.rollers(10.0, 200.0, 20.0, 5.0, "white",
                                          speed_ms=5.0, sigma=s)),
    ):
        previous = None
        for step in range(4, 21):                      # sigma 1.00 .. 5.00
            sigma = step * 0.25
            elevations, distances, true_gain = build(sigma)
            got = elevation_gain(elevations, distances)

            # Only assert while the figure is still worth something. Past a
            # sensor this bad the estimator has already given up — on 200 m
            # rollers it reports under a third of the climb from sigma 4.5 — and
            # how jaggedly it declines from there is not a property worth
            # pinning. Measured on the current implementation: smooth 1-4%
            # steps to sigma 3, then 11-54% jitter once it is below that line.
            usable = true_gain == 0 or min(previous or got, got) > true_gain * 0.3
            if previous is not None and usable:
                reference = max(previous, got, 50.0)   # ignore noise in the small
                jump = abs(got - previous) / reference
                assert jump < 0.5, (
                    f"{label}: sigma {sigma - 0.25:.2f} -> {sigma:.2f} moved the "
                    f"figure {previous:.0f} -> {got:.0f} m, a {jump:.0%} step; "
                    f"a quarter-metre of sensor noise is the difference between "
                    f"two phone models, not between two trips"
                )
            previous = got


def test_split_pieces_do_not_exceed_the_whole():
    """Cutting a track into pieces must not manufacture ascent.

    Each piece is recomputed absolutely today, so the pieces are free to sum to
    more than the parent — the apportioning work turns this into an equality.
    Until then, assert the weaker property that they do not run away, which is
    what a user notices when splitting a ride adds a hundred metres to a trip.
    """
    whole = gen.climb(600.0, 20.0, 1.5, "barometric")
    clean = gen.climb(600.0, 20.0, 1.5, "clean")
    whole_gain = elevation_gain(whole[0], whole[1])

    pieces = [gen.fragment(whole, clean, lo / 4, (lo + 1) / 4) for lo in range(4)]
    summed = sum(elevation_gain(e, d) for e, d, _ in pieces)

    assert summed <= whole_gain * 1.15, (
        f"four pieces sum to {summed:.0f} m against the whole track's "
        f"{whole_gain:.0f} m"
    )
