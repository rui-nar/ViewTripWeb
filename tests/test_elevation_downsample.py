"""Tests for server-side elevation downsampling (low-res-first chart)."""
from __future__ import annotations

import math

from src.project.elevation_downsample import downsample_elevation


def test_short_profile_returned_unchanged():
    d = [0.0, 1.0, 2.0]
    e = [10.0, 20.0, 15.0]
    od, oe = downsample_elevation(d, e, max_points=300)
    assert od == d and oe == e
    # New lists, not the same objects (callers may mutate).
    assert od is not d and oe is not e


def test_downsamples_to_about_max_points():
    n = 5000
    d = [i * 0.01 for i in range(n)]
    e = [100 + 50 * math.sin(i / 30) for i in range(n)]
    od, oe = downsample_elevation(d, e, max_points=300)
    assert len(od) == len(oe)
    # ~max_points, with up to 2 extra for the forced global extremes.
    assert 300 <= len(od) <= 302
    assert len(od) < n


def test_preserves_endpoints():
    n = 2000
    d = [float(i) for i in range(n)]
    e = [float(i % 7) for i in range(n)]
    od, oe = downsample_elevation(d, e, max_points=100)
    assert od[0] == d[0] and oe[0] == e[0]
    assert od[-1] == d[-1] and oe[-1] == e[-1]


def test_preserves_global_min_and_max():
    n = 2000
    d = [float(i) for i in range(n)]
    e = [float(i % 11) for i in range(n)]
    # Inject a unique spike + dip that uniform sampling would likely miss.
    e[997] = 9999.0   # global max
    e[1003] = -9999.0  # global min
    od, oe = downsample_elevation(d, e, max_points=50)
    assert max(oe) == 9999.0, "global peak must survive downsampling"
    assert min(oe) == -9999.0, "global valley must survive downsampling"
    # And at the right x positions.
    assert od[oe.index(9999.0)] == 997.0
    assert od[oe.index(-9999.0)] == 1003.0


def test_output_x_is_monotonic_nondecreasing():
    n = 1500
    d = [i * 0.5 for i in range(n)]
    e = [math.cos(i / 13) for i in range(n)]
    od, _ = downsample_elevation(d, e, max_points=120)
    assert all(od[i] <= od[i + 1] for i in range(len(od) - 1))
