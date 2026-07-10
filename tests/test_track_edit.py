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
