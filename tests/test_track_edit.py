"""Pure-unit tests for the track-edit geometry helpers (issue #31).

Covers recompute_track_metrics (known coords → known distance / gain / hi-lo /
degenerate) and the align/re-derive point-list round trip.
"""
from __future__ import annotations

import pytest

from src.models.great_circle import haversine_km
from src.models.track_edit import (
    TrackPoint,
    align_points,
    elevation_gain,
    points_to_elevation_profile,
    points_to_polyline,
    recompute_track_metrics,
)


class TestRecomputeMetrics:
    def test_distance_matches_haversine(self):
        # Two points ~1 km apart; distance must equal the haversine in metres.
        p = [TrackPoint(48.0, 2.0, 100.0), TrackPoint(48.0, 2.0134, 110.0)]
        m = recompute_track_metrics(p)
        expected_m = haversine_km(48.0, 2.0, 48.0, 2.0134) * 1000.0
        assert m.distance == pytest.approx(expected_m, rel=1e-6)

    def test_elevation_gain_sums_positive_deltas(self):
        p = [
            TrackPoint(0.0, 0.0, 100.0),
            TrackPoint(0.0, 0.01, 150.0),   # +50
            TrackPoint(0.0, 0.02, 120.0),   # -30 (ignored)
            TrackPoint(0.0, 0.03, 170.0),   # +50
        ]
        m = recompute_track_metrics(p)
        assert m.total_elevation_gain == pytest.approx(100.0)
        assert m.elev_high == pytest.approx(170.0)
        assert m.elev_low == pytest.approx(100.0)

    def test_start_and_end_latlng(self):
        p = [TrackPoint(1.0, 2.0, 0.0), TrackPoint(3.0, 4.0, 0.0)]
        m = recompute_track_metrics(p)
        assert m.start_latlng == [1.0, 2.0]
        assert m.end_latlng == [3.0, 4.0]

    def test_times_apportioned_to_retained_distance(self):
        # Retain half the distance → half the times.
        p = [TrackPoint(0.0, 0.0, 0.0), TrackPoint(0.0, 0.01, 0.0)]
        full = recompute_track_metrics(p)
        m = recompute_track_metrics(
            p,
            original_distance_m=full.distance * 2,
            original_moving_time=1000,
            original_elapsed_time=1200,
        )
        assert m.moving_time == pytest.approx(500, abs=1)
        assert m.elapsed_time == pytest.approx(600, abs=1)

    def test_average_speed_from_apportioned_time(self):
        p = [TrackPoint(0.0, 0.0, 0.0), TrackPoint(0.0, 0.01, 0.0)]
        full_dist = recompute_track_metrics(p).distance
        m = recompute_track_metrics(
            p, original_distance_m=full_dist,
            original_moving_time=100, original_elapsed_time=100)
        assert m.average_speed == pytest.approx(m.distance / m.moving_time)

    def test_empty_points_degenerate(self):
        m = recompute_track_metrics([])
        assert m.distance == 0.0
        assert m.start_latlng is None
        assert m.end_latlng is None
        assert m.moving_time == 0

    def test_single_point_degenerate(self):
        m = recompute_track_metrics([TrackPoint(1.0, 2.0, 50.0)])
        assert m.distance == 0.0
        assert m.start_latlng == [1.0, 2.0]
        assert m.elev_high == 50.0

    def test_no_elevation_yields_none_hi_lo(self):
        p = [TrackPoint(0.0, 0.0, None), TrackPoint(0.0, 0.01, None)]
        m = recompute_track_metrics(p)
        assert m.total_elevation_gain == 0.0
        assert m.elev_high is None
        assert m.elev_low is None


class TestAlignRoundTrip:
    def test_align_then_reencode_polyline(self):
        pts = [TrackPoint(48.0, 2.0), TrackPoint(48.001, 2.001), TrackPoint(48.002, 2.002)]
        poly = points_to_polyline(pts)
        aligned = align_points(poly, None)
        assert len(aligned) == 3
        for a, b in zip(aligned, pts):
            assert a.lat == pytest.approx(b.lat, abs=1e-5)
            assert a.lng == pytest.approx(b.lng, abs=1e-5)

    def test_align_interpolates_elevation_onto_polyline(self):
        pts = [TrackPoint(48.0, 2.0, 100.0), TrackPoint(48.0, 2.02, 200.0)]
        poly = points_to_polyline(pts)
        ep = points_to_elevation_profile(pts)
        aligned = align_points(poly, ep)
        assert aligned[0].elev == pytest.approx(100.0, abs=1.0)
        assert aligned[-1].elev == pytest.approx(200.0, abs=1.0)

    def test_align_empty_polyline(self):
        assert align_points(None, None) == []
        assert align_points("", None) == []

    def test_points_to_elevation_profile_none_when_no_elev(self):
        pts = [TrackPoint(0.0, 0.0, None), TrackPoint(0.0, 0.01, None)]
        assert points_to_elevation_profile(pts) is None

    def test_points_to_polyline_empty(self):
        assert points_to_polyline([]) is None


class TestElevationGain:
    """Regression tests for issue #260 — gain used to be a raw sum of positive
    deltas, which counts sensor noise as climbing. The error only ever adds, so
    it grows with the sample count: a 6000-sample track with a true 600 m climb
    and ±1.2 m of ordinary jitter reported 4094 m.

    The second wave of cases guards the fix's own failure mode. A window
    measured in SAMPLES is a different physical width per recording rate, and an
    11-sample window over a planned route exported at one point per 100 m spans
    a kilometre — which reported 3 m of climb on a route holding 600 m of it.
    """

    @staticmethod
    def _climb(n=6000, peak=600.0, sigma=1.2, spacing_km=0.0055, seed=7):
        """One up-then-down climb under Gaussian noise, plus its distances."""
        import random

        random.seed(seed)
        elevs = [
            200.0 + peak * (1 - abs(2 * (i / (n - 1)) - 1)) + random.gauss(0, sigma)
            for i in range(n)
        ]
        return elevs, [i * spacing_km for i in range(n)]

    @staticmethod
    def _hills(count, height, samples, spacing_km, sigma=0.0, seed=3):
        """*count* identical triangular hills — straight flanks, sharp peaks."""
        import random

        random.seed(seed)
        elevs = []
        for _ in range(count):
            for i in range(samples):
                half = samples / 2
                frac = i / half if i < half else (samples - i) / half
                elevs.append(300.0 + height * frac + random.gauss(0, sigma))
        return elevs, [i * spacing_km for i in range(len(elevs))]

    @staticmethod
    def _sine_hills(count, height, samples, spacing_km, sigma=0.0, seed=3):
        """*count* identical sinusoidal hills — the shape rolling terrain has.

        Triangles have straight flanks, so every second difference along them is
        zero no matter how coarse the sampling. That is exactly the blind spot
        issue #376 is about, which is why the triangular fixture could never
        show it: real terrain bends, second differences grow with the square of
        the spacing on a bend, and a clean curved route therefore measured as
        noisy and had its rollers erased.
        """
        import math
        import random

        random.seed(seed)
        elevs = []
        for _ in range(count):
            for i in range(samples):
                phase = 2 * math.pi * i / samples
                elevs.append(300.0 + height / 2.0 * (1 - math.cos(phase))
                             + random.gauss(0, sigma))
        return elevs, [i * spacing_km for i in range(len(elevs))]

    @staticmethod
    def _flat(n, sigma, spacing_km, hold=1, seed=11):
        """Flat ground under Gaussian noise — true gain zero.

        ``hold`` repeats each altitude reading that many samples, the way a
        device whose barometer updates slower than its GPS fix does.
        """
        import random

        random.seed(seed)
        elevs = []
        reading = 100.0
        for i in range(n):
            if i % hold == 0:
                reading = 100.0 + random.gauss(0, sigma)
            elevs.append(reading)
        return elevs, [i * spacing_km for i in range(n)]

    def test_noisy_track_reports_the_real_climb(self):
        elevs, dists = self._climb()
        assert elevation_gain(elevs, dists) == pytest.approx(600.0, abs=25.0)

    def test_raw_delta_sum_would_be_several_times_worse(self):
        """Pins the size of the defect from both ends, so neither the old
        inflation nor an implementation that just returns 0 can pass."""
        elevs, dists = self._climb()
        raw = sum(max(0.0, b - a) for a, b in zip(elevs, elevs[1:]))
        assert raw > 3000.0                        # what the old code returned
        assert 575.0 < elevation_gain(elevs, dists) < raw / 5

    def test_sparse_planned_route_keeps_its_hills(self):
        """A route planner exports ~1 point per 100 m of DEM elevation. Under a
        sample-counted window every hill vanished (600 m of climb read as 3 m);
        the window is distance-based, so a series this sparse is left alone."""
        elevs, dists = self._hills(30, height=20.0, samples=12, spacing_km=0.1)
        assert elevation_gain(elevs, dists) == pytest.approx(600.0, abs=30.0)

    def test_clean_small_rollers_are_counted(self):
        """DEM elevations carry no noise, so the band drops to its floor and
        4 m rollers survive — a fixed 3 m band would have discarded them."""
        elevs, dists = self._hills(50, height=4.0, samples=10, spacing_km=0.05)
        assert elevation_gain(elevs, dists) > 100.0

    def test_noise_on_flat_ground_is_not_climbing(self):
        import random

        random.seed(11)
        n = 3000
        for sigma in (1.2, 3.0):
            elevs = [100.0 + random.gauss(0, sigma) for _ in range(n)]
            dists = [i * 0.0055 for i in range(n)]
            assert elevation_gain(elevs, dists) < 15.0, (
                f"flat ground at sigma={sigma} must not accumulate ascent"
            )

    def test_rolling_terrain_is_under_reported_but_not_erased(self):
        """Honest about a real limit: hills only a few metres tall sit close to
        the noise, and the band costs roughly its own height per hill. The
        figure is conservative — what it must never be again is inflated.

        Sinusoidal hills, not the triangles this used to use (issue #376).
        Triangular flanks are straight, so they carry no curvature for the noise
        estimate to trip over and the old bound of 150-600 m was wide enough to
        hide the miss anyway. With real curvature the previous estimator read
        the bend itself as noise and reported 377 m of this true 600.
        """
        elevs, dists = self._sine_hills(100, height=6.0, samples=60,
                                        spacing_km=0.005, sigma=1.2)
        gain = elevation_gain(elevs, dists)
        assert 400.0 < gain < 520.0

    def test_sparse_noisy_ground_is_not_phantom_climb(self):
        """Issue #376, first false premise: sparse sampling was taken to mean
        route-planner DEM output with no sensor noise in it, so smoothing was
        skipped outright and a 5 m band was the only defence left.

        Spacing does not identify the source. A non-barometric phone, a Garmin
        on smart recording and a track simplified before upload are all sparse
        AND noisy. 30 km of flat ground at 40 m spacing reported 188 m of climb
        at sigma 2, 675 m at sigma 3 and 1639 m at sigma 5.
        """
        for sigma in (2.0, 3.0, 5.0):
            elevs, dists = self._flat(750, sigma, spacing_km=0.04)
            gain = elevation_gain(elevs, dists)
            assert gain < 50.0, (
                f"30 km of flat ground at 40 m spacing, sigma={sigma}: "
                f"reported {gain:.0f} m of climb"
            )

    def test_clean_curved_route_keeps_its_rollers(self):
        """Issue #376, second false premise: that second differences are near
        zero for a smooth series however steep. True on a straight flank, false
        on a bend — they scale with the square of the sample spacing — so a
        CLEAN curved route at 100 m spacing measured as sigma 2 and earned a
        band wide enough to swallow its rollers whole.

        Rollers up to roughly twice the band vanish entirely, because the
        reference elevation ends up sitting mid-oscillation: 10 m hills over
        600 m reported 253 m of their true 500, and 4 m hills over 500 m
        reported 0 of their true 240.
        """
        elevs, dists = self._sine_hills(50, height=10.0, samples=6,
                                        spacing_km=0.1)
        assert elevation_gain(elevs, dists) > 400.0      # true 500

        elevs, dists = self._sine_hills(60, height=4.0, samples=5,
                                        spacing_km=0.1)
        assert elevation_gain(elevs, dists) > 150.0      # true 240

    def test_held_altitude_readings_are_not_climbing(self):
        """Issue #376, third symptom of the same root cause: a device whose
        altitude updates slower than its position writes runs of identical
        values. Every difference taken inside a run is exactly zero, so the
        median collapsed, the band dropped to its 1 m floor, and the full-sized
        steps between readings were all counted as climb.

        30 km of flat ground with altitude held for 5 samples reported 167 m at
        sigma 1.2, 385 m at sigma 2 and 680 m at sigma 3.
        """
        for hold in (5, 10):
            for sigma in (1.2, 2.0, 3.0):
                elevs, dists = self._flat(6000, sigma, spacing_km=0.005,
                                          hold=hold)
                gain = elevation_gain(elevs, dists)
                assert gain < 50.0, (
                    f"altitude held for {hold} samples at sigma={sigma}: "
                    f"reported {gain:.0f} m of climb on flat ground"
                )

    def test_quantised_barometric_input_matches_unquantised(self):
        """Barometric altitude arrives rounded — to 0.1, 0.2 or a whole metre.

        That also produces runs of equal values, and the run-aware noise
        estimate must not mistake them for a slow sensor: a quantised reading
        still changes almost every sample, so its runs are one or two long.
        This held before issue #376 as well; it is here so that the stride
        logic added for held readings cannot quietly break it.
        """
        elevs, dists = self._climb()
        baseline = elevation_gain(elevs, dists)
        for step in (0.1, 0.2, 1.0):
            quantised = [round(e / step) * step for e in elevs]
            assert elevation_gain(quantised, dists) == pytest.approx(
                baseline, rel=0.02), f"quantising to {step} m moved the figure"

    def test_long_track_stays_linear(self):
        """Both halves grew in issue #376 — the noise estimate differences the
        series five times over and the smoothing window widens with the noise —
        so pin that neither turned into a per-sample rescan. 200k samples is a
        long dense ride; this measures ~0.2 s, the same as before the change.
        """
        import random
        import time

        random.seed(1)
        n = 200_000
        elevs = [100.0 + i * 0.002 + random.gauss(0, 1.2) for i in range(n)]
        dists = [i * 0.0055 for i in range(n)]

        start = time.time()
        elevation_gain(elevs, dists)
        elapsed = time.time() - start
        assert elapsed < 1.0, f"elevation_gain took {elapsed:.2f}s at {n}"

    def test_steady_climb_is_counted_in_full(self):
        """A clean ramp comes back within ~1%: the clamped window flattens the
        two ends slightly, and the hysteresis band can leave up to one band's
        worth uncounted at the finish."""
        elevs = [100.0 + i for i in range(500)]       # +1 m per sample, 499 m
        dists = [i * 0.0055 for i in range(500)]
        assert elevation_gain(elevs, dists) == pytest.approx(499.0, rel=0.02)

    def test_short_series_keeps_its_real_steps(self):
        assert elevation_gain([100.0, 150.0, 120.0, 170.0],
                              [0.0, 0.5, 1.0, 1.5]) == pytest.approx(100.0)

    def test_pure_descent_yields_no_gain(self):
        elevs = [500.0 - i for i in range(500)]
        assert elevation_gain(elevs, [i * 0.0055 for i in range(500)]) == 0.0

    def test_works_without_distances(self):
        """Both callers pass distances; this is the defensive path.

        Without them there is no window to average over, so the band alone does
        the work: bounded and far better than the raw sum, but not accurate.
        Asserted as a bound rather than a value, because claiming otherwise
        would promise a precision this path cannot deliver."""
        elevs, _ = self._climb()
        raw = sum(max(0.0, b - a) for a, b in zip(elevs, elevs[1:]))
        assert 600.0 <= elevation_gain(elevs) < raw / 3

    def test_degenerate_series(self):
        assert elevation_gain([]) == 0.0
        assert elevation_gain([100.0]) == 0.0
        assert elevation_gain([100.0, 100.0]) == 0.0

    def test_points_without_elevation_do_not_invent_a_climb(self):
        """A gap in elevation must leave a gap in the series, not a plunge to
        sea level: recompute drops those points and keeps the distance."""
        pts = []
        for i in range(300):
            elev = 500.0 + (i * 0.1 if i < 150 else (300 - i) * 0.1)
            if i in (100, 101, 102):
                elev = None
            pts.append(TrackPoint(45.0 + i * 1e-5, 6.0 + i * 1e-5, elev))
        assert recompute_track_metrics(pts).total_elevation_gain < 30.0


class TestAlignPointsPerformance:
    """Regression test for issue #45 — save/split on a long, dense activity
    (tens of thousands of GPS points, e.g. a multi-hour ride) used to hang past
    the client's request timeout. Root cause: align_points' elevation
    interpolation rescanned the elevation array from the start for every
    polyline point, making one alignment O(N*M) — 20+ seconds at ~40k points —
    even though the write itself succeeded a moment later (visible on reload),
    which is what made this look like a DB-lock hang rather than a slow
    computation. Fixed via binary search (bisect) instead of a linear rescan.
    """

    def test_large_track_aligns_quickly(self):
        import random
        import time

        random.seed(7)
        n = 30_000
        lat, lng = 48.0, 2.0
        pts = []
        for _ in range(n):
            lat += random.uniform(-0.0005, 0.0005)
            lng += random.uniform(-0.0005, 0.0005)
            pts.append(TrackPoint(lat, lng))
        poly = points_to_polyline(pts)
        dist_km = [i * 0.01 for i in range(n)]
        elev_m = [100.0 + (i % 50) for i in range(n)]

        start = time.time()
        aligned = align_points(poly, (dist_km, elev_m))
        elapsed = time.time() - start

        assert len(aligned) == n
        # The old O(N*M) scan took 20+ seconds at this size; a healthy
        # implementation finishes in well under a second.
        assert elapsed < 3.0, f"align_points took {elapsed:.2f}s for {n} points"
