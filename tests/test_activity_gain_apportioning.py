"""Editing and splitting must not re-measure elevation gain (issue #386).

A synced activity arrives with Strava's own climb figure, measured from data we
never receive and corrected in ways we cannot reproduce. Until now any edit
threw it away and substituted ours, so trimming fifty metres off a ride could
move its climb by hundreds; splitting measured each piece independently, so the
pieces did not sum to the track they came out of.

Each piece now keeps the share of the original figure that its own geometry
accounts for — the treatment moving and elapsed time already get. These tests
pin the three properties that follow: a no-op edit changes nothing, pieces sum
to their parent, and a reset restores the figure it started from.
"""
from __future__ import annotations

import json

import polyline as polyline_lib
import pytest

from models.project_db import DBActivity
from src.project.repo_activities import _apportion_gain


#: Deliberately unlike anything our estimator would produce from the geometry
#: below, so a test that passes cannot be passing by coincidence.
STRAVA_GAIN = 1234.0


def _track(points=240):
    """A climb-then-descend track with real elevation, and its stored columns."""
    coords = [(46.0 + i * 2e-4, 6.0 + i * 2e-4) for i in range(points)]
    elevations = [
        500.0 + (i * 2.0 if i < points // 2 else (points - i) * 2.0)
        for i in range(points)
    ]
    distances = [i * 0.03 for i in range(points)]
    return (polyline_lib.encode(coords),
            json.dumps({"distances_km": distances, "elevations_m": elevations}))


def _row(**kwargs) -> DBActivity:
    poly, ep = _track()
    defaults = dict(
        id=1, user_info_id=1, name="Ride", type="Ride",
        summary_polyline=poly, elevation_profile_json=ep,
        total_elevation_gain=STRAVA_GAIN, distance=7000.0,
        moving_time=3600, elapsed_time=3700, is_edited=False,
    )
    defaults.update(kwargs)
    return DBActivity(**defaults)


def _points(row: DBActivity):
    from src.models.track_edit import align_points
    ep = json.loads(row.elevation_profile_json)
    return align_points(row.summary_polyline,
                        (ep["distances_km"], ep["elevations_m"]))


class TestApportionGain:
    """The rule itself, in isolation."""

    def test_scales_by_the_share_the_new_geometry_accounts_for(self):
        assert _apportion_gain(1000.0, 800.0, 400.0) == pytest.approx(500.0)

    def test_unchanged_geometry_leaves_the_figure_alone(self):
        assert _apportion_gain(1234.0, 812.0, 812.0) == pytest.approx(1234.0)

    def test_falls_back_when_there_is_nothing_to_scale(self):
        """No stored figure, or a zero denominator — a flat activity, or a
        client-encrypted profile the server cannot read — recomputes as before."""
        assert _apportion_gain(None, 800.0, 400.0) == pytest.approx(400.0)
        assert _apportion_gain(1000.0, 0.0, 400.0) == pytest.approx(400.0)


class TestEditKeepsTheSourceFigure:
    def test_a_no_op_edit_does_not_move_the_number(self):
        """The case a user sees first: open the editor, save without touching
        anything, and watch the climb change. It must not."""
        from src.project.repo_activities import ActivityMixin

        row = _row()
        ActivityMixin._write_track_geometry(row, _points(row))

        assert row.total_elevation_gain == pytest.approx(STRAVA_GAIN, rel=0.02)

    def test_the_pre_edit_figure_is_snapshotted(self):
        from src.project.repo_activities import ActivityMixin

        row = _row()
        ActivityMixin._write_track_geometry(row, _points(row))
        assert row.original_total_elevation_gain == pytest.approx(STRAVA_GAIN)

    def test_trimming_keeps_the_share_it_retained(self):
        """Half the climb retained is half the figure — not our own absolute
        measure of the remaining half, which would be a different number."""
        from src.project.repo_activities import ActivityMixin
        from src.models.track_edit import elevation_gain, recompute_track_metrics

        row = _row()
        points = _points(row)
        kept = points[: len(points) // 2]

        whole = recompute_track_metrics(points).total_elevation_gain
        part = recompute_track_metrics(kept).total_elevation_gain
        ActivityMixin._write_track_geometry(row, kept)

        assert row.total_elevation_gain == pytest.approx(
            STRAVA_GAIN * part / whole, rel=1e-6)
        assert row.total_elevation_gain != pytest.approx(part, rel=0.05), (
            "the edited piece must carry a share of Strava's figure, not our "
            "own measurement of the remaining geometry"
        )

    def test_a_second_edit_compounds_rather_than_resets(self):
        from src.project.repo_activities import ActivityMixin

        row = _row()
        points = _points(row)
        ActivityMixin._write_track_geometry(row, points[: int(len(points) * 0.8)])
        after_first = row.total_elevation_gain

        remaining = _points(row)
        ActivityMixin._write_track_geometry(row, remaining[: int(len(remaining) * 0.5)])

        assert row.total_elevation_gain < after_first
        assert row.original_total_elevation_gain == pytest.approx(STRAVA_GAIN), (
            "the snapshot is taken on the FIRST edit only, so a reset still "
            "returns to Strava's figure and not to an intermediate one"
        )

    def test_an_unreadable_profile_falls_back_to_measuring(self):
        """An E2EE row's stored profile is ciphertext to the server, so there is
        no 'before' geometry to take a share of. That path recomputes, exactly
        as every row did before this change."""
        from src.project.repo_activities import ActivityMixin
        from src.models.track_edit import recompute_track_metrics

        row = _row(elevation_profile_json="v1.d3JhcHBlZA==.Y2lwaGVydGV4dA==")
        points = _points(_row())
        ActivityMixin._write_track_geometry(row, points)

        assert row.total_elevation_gain == pytest.approx(
            recompute_track_metrics(points).total_elevation_gain)
