"""Gates over the terrain-oracle benchmark (issue #386).

The cases — what each input is, what it should report, and why — live in
:mod:`tests.elevation_bench.terrain_cases`. This module only asserts them.

The history that makes these necessary: elevation gain has been rewritten four
times, and every round was measured against whichever fixtures were to hand,
shipped, and then turned out to have wrecked a class nobody had generated. PR
#389 measured correlated noise correctly and erased up to 100% of a real 1000 m
day for it.

So the gate that matters most here is not accuracy — it is the **no-op**:
wherever the terrain model sees relief, the figure must be exactly what the
recording alone produces. That is the only thing that makes introducing a second
measurement safe, and it is asserted as equality rather than as a bound.
"""
from __future__ import annotations

import pytest

from src.models.track_edit import (
    TERRAIN_RELIEF_M,
    elevation_gain,
    terrain_corrected_gain,
)
from tests.elevation_bench import terrain as ter
from tests.elevation_bench.terrain_cases import FIXED, NO_OP, WATCH

#: Several draws of the correlated noise, so no bound is pinned to one of them.
SEEDS = (3, 11, 17, 29, 41)


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("case", FIXED, ids=lambda c: c.key)
def test_the_oracle_removes_the_phantom(case, seed):
    track = case.build(seed)
    got = terrain_corrected_gain(track.recorded, track.terrain, track.distances_km)
    ships = elevation_gain(track.recorded, track.distances_km)

    detail = (
        f"{case.label} (seed {seed}): the oracle reported {got:.0f} m where the "
        f"recording alone reports {ships:.0f} m, against a true "
        f"{track.true_gain:.0f} m and a model ceiling of "
        f"{track.model_ceiling:.0f} m"
        + (f" — {case.note}" if case.note else "")
    )
    if case.low is not None:
        assert got >= case.low, f"{detail}; expected at least {case.low:.0f}"
    if case.high is not None:
        assert got <= case.high, f"{detail}; expected at most {case.high:.0f}"


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("case", NO_OP, ids=lambda c: c.key)
def test_the_oracle_is_invisible_where_there_is_terrain(case, seed):
    """Bit-identical, not merely close.

    Every window has relief, so every window contributes the recording's own
    steps and the spliced series must BE the recording. Any difference means a
    boundary sample was dropped or a verdict misfired — and the first version of
    this code did slice ``[lo:hi]``, silently dropping the step across each
    window boundary (39 of them on a 20 km track), which read 766 m where the
    recording read 858 m. A loss on exactly the class this protects.
    """
    track = case.build(seed)
    got = terrain_corrected_gain(track.recorded, track.terrain, track.distances_km)
    ships = elevation_gain(track.recorded, track.distances_km)

    assert got == pytest.approx(ships, abs=1e-9), (
        f"{case.label} (seed {seed}): the oracle changed a figure it must not "
        f"touch — {ships:.3f} m became {got:.3f} m"
        + (f" — {case.note}" if case.note else "")
    )


@pytest.mark.parametrize("case", WATCH, ids=lambda c: c.key)
def test_watched_case_runs(case):
    """The measured-but-unfixed cases still have to run.

    They carry no bound — asserting one would encode either a wrong answer or a
    permanent failure — but a generator that raises, or a series that makes the
    oracle return a non-number, is a real defect and would otherwise hide here
    until someone read the table.
    """
    track = case.build()
    got = terrain_corrected_gain(track.recorded, track.terrain, track.distances_km)

    assert got == got, f"{case.label} produced NaN"        # NaN != NaN
    assert 0.0 <= got < 1e6, f"{case.label} produced {got}"


def test_no_terrain_available_falls_back_to_the_recording():
    """A missing model is a normal state, not an error.

    The tile source has no SLA, and an end-to-end encrypted activity's geometry
    cannot be read by the server at all — so "no terrain" has to mean "report
    what we always reported", never a zero and never a raise.
    """
    track = ter.track_over(ter.flat_plain())
    expected = elevation_gain(track.recorded, track.distances_km)

    assert terrain_corrected_gain(
        track.recorded, [], track.distances_km) == expected
    assert terrain_corrected_gain(
        track.recorded, track.terrain[:-5], track.distances_km) == expected, (
        "a truncated model must be refused wholesale rather than lined up "
        "against the wrong points of the recording"
    )


def test_two_points_cannot_answer_the_relief_question():
    """A single step is not a window, so the recording stands.

    Three points, though, are enough — and the verdict on them is not a
    formality. 40 m of recorded climb across 200 m of flat-reading model is a
    20% grade: a 30 m model resolves that easily, so "no relief here" really
    does mean the 40 m was invented, and a short trimmed fragment gets the same
    correction a long track would. Falling back on 3 points instead would leave
    exactly the fragments a split produces uncorrected.
    """
    recorded = [100.0, 140.0, 130.0]
    terrain = [100.0, 100.0, 100.0]
    distances = [0.0, 0.1, 0.2]

    assert terrain_corrected_gain(recorded[:2], terrain[:2], distances[:2]) == (
        elevation_gain(recorded[:2], distances[:2]))
    assert terrain_corrected_gain(recorded, terrain, distances) == 0.0


def test_no_cliff_as_the_fix_degrades():
    """The figure must move smoothly as the horizontal error grows.

    #389's defining failure was a step change: a quarter-metre more sensor noise
    took the same road from 763 m to 23 m, so two people riding together with
    different phones got different trips. This approach has its own version of
    that risk — the coupling term grows with horizontal error, and a relief
    verdict could flip a whole window at once.
    """
    previous = None
    for tenths in range(10, 101, 10):                      # sigma_h 1.0 .. 10.0
        sigma_h = tenths / 10.0
        track = ter.track_over(ter.cross_slope(), sigma_h=sigma_h)
        got = terrain_corrected_gain(
            track.recorded, track.terrain, track.distances_km)

        if previous is not None:
            reference = max(previous, got, 50.0)           # ignore the small
            jump = abs(got - previous) / reference
            assert jump < 0.5, (
                f"horizontal noise {sigma_h - 1.0:.1f} -> {sigma_h:.1f} m moved "
                f"the figure {previous:.0f} -> {got:.0f} m, a {jump:.0%} step"
            )
        previous = got


def test_the_relief_threshold_is_what_decides_a_window():
    """Sanity on the mechanism itself, independent of any surface.

    A threshold of zero can never call a window flat, so the oracle must
    degenerate to the recording; an enormous one calls every window flat, so it
    must degenerate to the model. If either end does not hold, the verdict is
    not actually driving the splice and the gates above could be passing for
    some other reason.
    """
    track = ter.track_over(ter.flat_plain())
    ships = elevation_gain(track.recorded, track.distances_km)
    substitution = elevation_gain(track.terrain, track.distances_km)

    assert terrain_corrected_gain(
        track.recorded, track.terrain, track.distances_km,
        relief_m=0.0) == pytest.approx(ships, abs=1e-9)
    assert terrain_corrected_gain(
        track.recorded, track.terrain, track.distances_km,
        relief_m=1e6) == pytest.approx(substitution, abs=1e-9)
    assert ships > substitution + 100.0, (
        "this fixture is only meaningful while the recording and the model "
        "disagree wildly; they now report "
        f"{ships:.0f} m and {substitution:.0f} m"
    )
    assert TERRAIN_RELIEF_M > 0.0


def test_the_window_is_measured_in_distance_not_samples():
    """A sparse route and a 1 Hz walk must ask over the same length of ground.

    Counting samples instead is the mistake that erased planned routes in #376:
    a window fixed at N points spans 60 m of a dense recording and 4 km of a
    route sampled every 100 m.
    """
    dense = ter.track_over(ter.flat_plain(), spacing_m=5.0)
    sparse = ter.track_over(ter.flat_plain(), spacing_m=50.0)

    from src.models.track_edit import TERRAIN_WINDOW_M, _terrain_window_samples

    dense_samples = _terrain_window_samples(
        dense.distances_km, len(dense.recorded), TERRAIN_WINDOW_M)
    sparse_samples = _terrain_window_samples(
        sparse.distances_km, len(sparse.recorded), TERRAIN_WINDOW_M)

    assert dense_samples == pytest.approx(TERRAIN_WINDOW_M / 5.0, rel=0.05)
    assert sparse_samples == pytest.approx(TERRAIN_WINDOW_M / 50.0, abs=1)
    assert sparse_samples >= 3, "never fewer than three points to a verdict"


def test_distances_are_optional():
    """``elevation_gain`` takes the distance axis as optional, so this must too."""
    track = ter.track_over(ter.flat_plain())

    got = terrain_corrected_gain(track.recorded, track.terrain)

    assert got == got and got >= 0.0
    assert got < elevation_gain(track.recorded), (
        "even without a distance axis the phantom climb must come down"
    )
