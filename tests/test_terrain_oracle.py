"""Gates over the terrain-oracle benchmark (issue #386).

The cases — what each input is, what it should report, and why — live in
:mod:`tests.elevation_bench.terrain_cases`. This module only asserts them.

The history that makes these necessary: elevation gain has been rewritten four
times, and every round was measured against whichever fixtures were to hand,
shipped, and then turned out to have wrecked a class nobody had generated. PR
#389 measured correlated noise correctly and erased up to 100% of a real 1000 m
day for it.

So the gate that matters most here is not accuracy — it is the **no-op**:
wherever the terrain model sees relief, the figure must be what the recording
alone produces, to within floating point. That is the only thing that makes
introducing a second measurement safe.
"""
from __future__ import annotations

import pytest

from src.models.track_edit import (
    TERRAIN_RELIEF_M,
    TERRAIN_WINDOW_M,
    _terrain_windows,
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
    """Equal to within floating point, which is the strongest available claim.

    Not literally bit-identical: the splice rebuilds the series by accumulating
    steps from ``recorded[0]``, and ``x + (y - x) == y`` is exact only while
    consecutive elevations are within a factor of two of each other. On rollers
    around 100 m it is exact on every seed; move the same rollers to sea level
    and 27 of 50 seeds drift, by about 8e-13 m. Hence the 1e-9 bound rather
    than ``==``.

    Every window has relief, so every window contributes the recording's own
    steps and the spliced series must be the recording. Any difference beyond
    that drift means a boundary sample was dropped or a verdict misfired — and
    the first version of this code did slice ``[lo:hi]``, dropping the step
    across each window boundary (40 of them on a 20 km track), which read 764 m
    where the recording read 858 m. A loss on exactly the class this protects.
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


def test_every_window_covers_the_same_ground_within_one_track():
    """Asserted through the oracle, not through the helper.

    A window derived from the track's MEAN spacing means different lengths of
    ground in different places: one 1 Hz phone carried 5 km on foot at 1.4 m/s
    and ridden 15 km at 8 m/s has a mean of 5.4 m, so a fixed sample count asks
    the relief question over 190 m in the walk and 1088 m in the ride. That
    called 27 of 41 windows flat on a steady 1.5% drag and took 60 m off a
    figure that should not have moved at all.

    This test exists in this form because the version that checked the helper's
    arithmetic passed with the window count hard-coded to 100 — the distance
    claim was never exercised through the code that uses it.
    """
    track = ter.track_over_segments(
        ter.steady_grade(), [(5.0, 1.4, 1.4), (15.0, 8.0, 8.0)])
    spans = [
        (track.distances_km[hi - 1] - track.distances_km[lo]) * 1000.0
        for lo, hi in _terrain_windows(
            track.distances_km, len(track.recorded), TERRAIN_WINDOW_M)
    ]

    # Every window but the last covers a window's worth of ground, whatever the
    # recording rate was doing there.
    for spanned in spans[:-1]:
        assert spanned == pytest.approx(TERRAIN_WINDOW_M, rel=0.15), (
            f"windows span {min(spans[:-1]):.0f}-{max(spans[:-1]):.0f} m of "
            f"ground on one track"
        )

    # And the consequence: relief everywhere on a steady drag, so the oracle is
    # the exact no-op it claims to be even though the spacing changes 6x.
    assert terrain_corrected_gain(
        track.recorded, track.terrain, track.distances_km
    ) == pytest.approx(
        elevation_gain(track.recorded, track.distances_km), abs=1e-9)


def test_distances_are_optional():
    """``elevation_gain`` takes the distance axis as optional, so this must too."""
    track = ter.track_over(ter.flat_plain())

    got = terrain_corrected_gain(track.recorded, track.terrain)

    assert got == got and got >= 0.0
    assert got < elevation_gain(track.recorded), (
        "even without a distance axis the phantom climb must come down"
    )


def test_the_model_error_field_is_reproducible():
    """Golden values, because a fixture that redraws itself is not a fixture.

    `terrain_model`'s error was once keyed on ``hash(("phase", seed))``. Any
    hash of a value containing a str takes Python's PER-PROCESS salt, so the
    same seed drew a different field on every run: nothing failed, no test
    flaked — the WATCH rows are printed rather than asserted — and every figure
    measured from it went into a docstring as though it were reproducible. It
    took an outside reviewer running `python -m tests.elevation_bench` twice to
    notice.

    These constants are that bug's tripwire. If they move, either the field's
    construction changed deliberately — in which case re-derive every figure in
    `_relief`'s docstring and in the WATCH notes, because they all come from
    this field — or a salted hash has crept back in.
    """
    correlated = ter.track_over(
        ter.flat_plain(), seed=3, post_sigma_m=1.0, error_length_m=500.0)
    independent = ter.track_over(ter.flat_plain(), seed=3, post_sigma_m=1.5)

    assert [round(v, 6) for v in (correlated.terrain[0],
                                  correlated.terrain[1000],
                                  correlated.terrain[3999])] == [
        101.010753, 100.626776, 101.220474]
    assert [round(v, 6) for v in (independent.terrain[0],
                                  independent.terrain[1000])] == [
        98.453429, 101.215555]


def test_the_error_amplitude_means_the_same_thing_in_every_row():
    """`post_sigma_m` is what the TRACK sees, not a nominal knot deviation.

    The model is read bilinearly from four posts, and the blend damps the error
    by an amount that depends on how correlated those posts are — independent
    error lost about a quarter of its amplitude, error correlated over hundreds
    of metres lost none. A correlation-length sweep at a fixed nominal sigma was
    therefore partly an amplitude sweep, and read as a bigger effect than it is.
    """
    for kwargs in ({"post_sigma_m": 1.0},
                   {"post_sigma_m": 1.0, "error_length_m": 45.0},
                   {"post_sigma_m": 1.0, "error_length_m": 300.0},
                   {"post_sigma_m": 1.0, "error_length_m": 1500.0}):
        track = ter.track_over(ter.flat_plain(), seed=3, **kwargs)
        mean = sum(track.terrain) / len(track.terrain)
        deviation = (sum((v - mean) ** 2 for v in track.terrain)
                     / len(track.terrain)) ** 0.5

        assert deviation == pytest.approx(1.0, abs=0.02), (
            f"{kwargs} gives the track {deviation:.3f} m of model error where "
            f"1.0 was asked for"
        )
