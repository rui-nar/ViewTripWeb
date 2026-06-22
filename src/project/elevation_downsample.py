"""Server-side elevation-profile downsampling for the low-res-first chart.

The elevation chart only ever renders ~300 points (it LTTB-downsamples on the
client), and the full profile is ~12 MB — slow to read off the NAS on load. So
we precompute a small downsampled profile per activity and serve it first; the
full profile then loads lazily in the background. See the elevation
low-res-first plan / [[project_pending]].
"""
from __future__ import annotations

from typing import List, Tuple

# Target point count for the low-res profile. Matches the client chart's render
# cap (_kMaxChartPoints) so the low-res overview is visually identical to the
# full profile after the client's own downsample.
DEFAULT_MAX_POINTS = 300


def downsample_elevation(
    distances_km: List[float],
    elevations_m: List[float],
    max_points: int = DEFAULT_MAX_POINTS,
) -> Tuple[List[float], List[float]]:
    """Downsample a ``(distances_km, elevations_m)`` profile to ~``max_points``.

    Uses Largest-Triangle-Three-Buckets (preserves visual shape) and always
    keeps the first/last points plus the global min & max elevation, so the
    chart's silhouette and y-axis range are correct before the full profile
    arrives. Returns the (possibly unchanged) profile as new lists.
    """
    n = min(len(distances_km), len(elevations_m))
    if n <= max_points or n <= 2 or max_points < 3:
        return list(distances_km[:n]), list(elevations_m[:n])

    idx = set(_lttb_indices(distances_km, elevations_m, n, max_points))
    # Guarantee the true extremes survive (LTTB may not pick them).
    idx.add(min(range(n), key=lambda i: elevations_m[i]))
    idx.add(max(range(n), key=lambda i: elevations_m[i]))
    final = sorted(idx)
    return [distances_km[i] for i in final], [elevations_m[i] for i in final]


def _lttb_indices(
    xs: List[float], ys: List[float], n: int, threshold: int
) -> List[int]:
    """Indices selected by Largest-Triangle-Three-Buckets. O(n)."""
    out = [0]
    a = 0
    every = (n - 2) / (threshold - 2)
    for i in range(threshold - 2):
        # Centroid of the next bucket — the "future" anchor.
        ns = int((i + 1) * every) + 1
        ne = min(int((i + 2) * every) + 1, n)
        cnt = max(ne - ns, 1)
        avg_x = sum(xs[ns:ne]) / cnt
        avg_y = sum(ys[ns:ne]) / cnt
        # Current bucket — pick the point forming the largest triangle with the
        # previously selected point (a) and the next-bucket centroid.
        cs = int(i * every) + 1
        ce = min(int((i + 1) * every) + 1, n)
        ax, ay = xs[a], ys[a]
        max_area = -1.0
        best = cs
        for j in range(cs, ce):
            area = abs((ax - avg_x) * (ys[j] - ay) - (ax - xs[j]) * (avg_y - ay))
            if area > max_area:
                max_area = area
                best = j
        out.append(best)
        a = best
    out.append(n - 1)
    return out
