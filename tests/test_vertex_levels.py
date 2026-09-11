"""Simplify once, serve every level — issue #369.

`simplify_for_zoom` runs a Ramer-Douglas-Peucker pass per request, which for a
219-activity trip is 1-3.7 s of GIL-holding Python at *every* level, on the
request path. `vertex_levels` moves that to one pass per line, after which a
level is a list comprehension.

The whole design rests on one claim: **filtering by level is the same set RDP
would keep at that level's tolerance**. That is what these pin, by comparing
against `simplify_for_zoom` itself at every level the endpoints accept, on the
shapes most likely to break it — not just on well-behaved tracks.
"""
from __future__ import annotations

import math
import random

import pytest

from src.models.simplify import (
    MAX_ZOOM_LEVEL,
    MIN_POINTS,
    NEVER_KEPT,
    PREPARED_GEO_VERSION,
    filter_to_level,
    simplify_for_zoom,
    vertex_levels,
    working_set,
)

LEVELS = range(0, MAX_ZOOM_LEVEL + 1)


def _line(points):
    """A lon/lat line rounded like a decoded polyline.

    Every activity reaches the geo endpoints via `polyline.decode`, which
    yields 5 decimals. Building fixtures at full float precision makes lines
    wigglier than anything production holds and quietly inflates both the
    retained-point counts and the payload.
    """
    return [[round(lon, 5), round(lat, 5)] for lat, lon in points]


def _smooth(n=3000, seed=0):
    rng = random.Random(seed)
    return _line(
        (
            45.0 + 0.02 * math.sin(i / 400.0) + rng.gauss(0, 0.000015),
            7.0 + i * 0.00005 + 0.01 * math.cos(i / 550.0) + rng.gauss(0, 0.000015),
        )
        for i in range(n)
    )


def _sawtooth(n=3000):
    """RDP's worst case: every interior vertex deviates from its neighbours.

    Named explicitly because a sawtooth fixture retained 419k of 876k points
    while a realistic track retains 166k, which made an early measurement of
    this work 15x too slow. It is a bad fixture for *timing* and a good one for
    *correctness*, which is why it is here and not in a benchmark.
    """
    return _line((45.0 + (i % 2) * 0.0002, 7.0 + i * 0.00005) for i in range(n))


CASES = {
    "smooth": _smooth(),
    "sawtooth": _sawtooth(),
    "straight": _line((45.0, 7.0 + i * 0.0001) for i in range(2000)),
    "identical_points": _line((45.0, 7.0) for _ in range(500)),
    "collinear_with_duplicates": _line(
        (45.0, 7.0 + (i // 2) * 0.0001) for i in range(1600)
    ),
    "single_spike": _line(
        (45.5 if i == 500 else 45.0, 7.0 + i * 0.0001) for i in range(1000)
    ),
    "closed_loop": _line(
        (45 + 0.01 * math.sin(i / 100.0), 7 + 0.01 * math.cos(i / 100.0))
        for i in list(range(1200)) + [0]
    ),
    "pure_noise": _smooth(n=2500, seed=9),
    "high_latitude": _line(
        (78.0 + 0.01 * math.sin(i / 90.0), 15.0 + i * 0.00008) for i in range(2000)
    ),
    "near_antimeridian": _line(
        (10.0 + 0.005 * math.sin(i / 70.0), 179.9 + i * 0.00001) for i in range(1500)
    ),
    # Around the MIN_POINTS floor, where filter_to_level must fall back exactly
    # as simplify_for_zoom does.
    "two_points": _line([(45.0, 7.0), (45.1, 7.1)]),
    "three_points": _line([(45.0, 7.0), (45.05, 7.2), (45.1, 7.1)]),
    "at_floor": _line((45 + i * 0.001, 7 + i * 0.001) for i in range(MIN_POINTS)),
    "just_over_floor": _line(
        (45 + i * 0.001, 7 + i * 0.001) for i in range(MIN_POINTS + 1)
    ),
    "elevation_third_element": [
        [7.0 + i * 0.0001, 45.0 + 0.001 * math.sin(i / 50.0), 100.0 + i]
        for i in range(600)
    ],
}


@pytest.mark.parametrize("name", sorted(CASES))
@pytest.mark.parametrize("level", LEVELS)
def test_filtering_by_level_matches_simplifying_at_that_level(name, level):
    """The identity, at every level the endpoints accept, on every shape.

    This is the test the persistence work in #369 is allowed to rely on. If it
    fails, the stored bytes are not a substitute for the RDP pass and nothing
    downstream is safe.
    """
    poly = working_set(CASES[name])
    assert filter_to_level(poly, vertex_levels(poly), level) == simplify_for_zoom(
        poly, level
    )


def test_a_long_track_is_compared_on_its_working_set_not_its_original():
    """`vertex_levels` is defined on the working set, and that loses nothing.

    `simplify_for_zoom` strides to MAX_INPUT_POINTS before simplifying, so the
    working set is all it ever reads — which is what lets a prepared line hold
    4,000 points instead of the track's full length.
    """
    long_track = _smooth(n=12000, seed=3)
    poly = working_set(long_track)
    assert len(poly) <= 4000
    for level in LEVELS:
        assert filter_to_level(poly, vertex_levels(poly), level) == simplify_for_zoom(
            long_track, level
        )


def test_endpoints_are_always_kept():
    poly = working_set(CASES["smooth"])
    levels = vertex_levels(poly)
    assert levels[0] == 0
    assert levels[-1] == 0
    for level in LEVELS:
        kept = filter_to_level(poly, levels, level)
        assert kept[0] == poly[0]
        assert kept[-1] == poly[-1]


def test_a_collinear_vertex_is_never_kept():
    """A point exactly on the line its neighbours describe has no level.

    Stored as NEVER_KEPT rather than dropped, so the byte array stays
    index-aligned with the working set it describes.
    """
    poly = working_set(CASES["straight"])
    levels = vertex_levels(poly)
    assert set(levels[1:-1]) == {NEVER_KEPT}


def test_levels_nest_so_a_deeper_zoom_is_a_superset():
    """Deeper levels only ever add points — the property clamping buys.

    Without clamping a vertex could out-rank the split that discarded it, and
    zooming in could *drop* a point that was visible zoomed out.
    """
    poly = working_set(CASES["smooth"])
    levels = vertex_levels(poly)
    previous = None
    for level in LEVELS:
        kept = [p for p, low in zip(poly, levels) if low <= level]
        if previous is not None:
            assert set(map(tuple, previous)) <= set(map(tuple, kept))
        previous = kept


def test_one_byte_per_vertex_and_all_values_are_storable():
    for name, case in CASES.items():
        poly = working_set(case)
        levels = vertex_levels(poly)
        assert len(levels) == len(poly), name
        assert all(0 <= b <= 255 for b in levels), name
        assert all(b <= MAX_ZOOM_LEVEL or b == NEVER_KEPT for b in levels), name


def test_the_byte_array_round_trips_through_bytes():
    poly = working_set(CASES["smooth"])
    levels = vertex_levels(poly)
    assert isinstance(levels, bytes)
    assert vertex_levels(poly) == bytes(bytearray(levels))
    for level in LEVELS:
        assert filter_to_level(poly, bytes(bytearray(levels)), level) == filter_to_level(
            poly, levels, level
        )


def test_a_line_under_three_points_has_one_level_each_and_is_served_whole():
    for name in ("two_points", "three_points"):
        poly = CASES[name]
        levels = vertex_levels(poly)
        assert len(levels) == len(poly)
        if len(poly) < 3:
            assert filter_to_level(poly, levels, 0) == poly


def test_the_version_is_an_int_the_store_can_compare():
    assert isinstance(PREPARED_GEO_VERSION, int)
    assert PREPARED_GEO_VERSION >= 1
