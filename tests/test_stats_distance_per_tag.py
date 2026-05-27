"""Tests for _compute_stats distance_per_tag field."""

from datetime import datetime

import pytest

from src.models.activity import Activity
from src.models.project import DayMeta, Project
from src.project.project_repo import _compute_stats


def _activity(aid: int, date_str: str, distance_m: float, atype: str = "ride") -> Activity:
    dt = datetime.fromisoformat(date_str)
    return Activity(
        id=aid,
        name=f"Activity {aid}",
        type=atype,
        distance=distance_m,
        moving_time=3600,
        elapsed_time=3600,
        total_elevation_gain=100.0,
        start_date=dt,
        start_date_local=dt,
        timezone="UTC",
        achievement_count=0,
        kudos_count=0,
        comment_count=0,
        athlete_count=1,
        photo_count=0,
        trainer=False,
        commute=False,
        manual=False,
        private=False,
        flagged=False,
        average_speed=5.0,
        max_speed=10.0,
        has_heartrate=False,
        pr_count=0,
        total_photo_count=0,
        has_kudoed=False,
    )


@pytest.fixture
def project_with_tags():
    p = Project(name="Tag Test")
    p.day_meta = {
        "2024-06-01": DayMeta(tags=["Alps"]),
        "2024-06-02": DayMeta(tags=["Alps"]),
        "2024-06-03": DayMeta(tags=["Pyrenees"]),
        "2024-06-04": DayMeta(tags=["Alps", "Pyrenees"]),  # multi-tag day
    }
    p.activities = [
        _activity(1, "2024-06-01", 50_000),
        _activity(2, "2024-06-02", 80_000),
        _activity(3, "2024-06-03", 60_000),
        _activity(4, "2024-06-04", 40_000),
    ]
    return p


class TestDistancePerTag:
    def test_keys_match_tags(self, project_with_tags):
        result = _compute_stats(project_with_tags)
        assert set(result["distance_per_tag"].keys()) == {"Alps", "Pyrenees"}

    def test_single_tag_day_counts_once(self, project_with_tags):
        result = _compute_stats(project_with_tags)
        dpt = result["distance_per_tag"]
        # Alps days: Jun-01 (50k) + Jun-02 (80k) + Jun-04 (40k) = 170k
        assert dpt["Alps"] == pytest.approx(170_000)

    def test_multi_tag_day_counts_for_each_tag(self, project_with_tags):
        result = _compute_stats(project_with_tags)
        dpt = result["distance_per_tag"]
        # Pyrenees days: Jun-03 (60k) + Jun-04 (40k) = 100k
        assert dpt["Pyrenees"] == pytest.approx(100_000)

    def test_non_ride_activities_excluded(self):
        p = Project(name="Mixed")
        p.day_meta = {"2024-06-01": DayMeta(tags=["Stage"])}
        p.activities = [
            _activity(1, "2024-06-01", 30_000, atype="ride"),
            _activity(2, "2024-06-01", 20_000, atype="run"),
        ]
        result = _compute_stats(p)
        assert result["distance_per_tag"]["Stage"] == pytest.approx(30_000)

    def test_empty_when_no_tags(self):
        p = Project(name="No Tags")
        p.day_meta = {"2024-06-01": DayMeta(tags=[])}
        p.activities = [_activity(1, "2024-06-01", 50_000)]
        result = _compute_stats(p)
        assert result["distance_per_tag"] == {}

    def test_ignores_tag_filter_arg(self, project_with_tags):
        """distance_per_tag is always computed over all activities."""
        filtered = _compute_stats(project_with_tags, tag_filter=["Alps"])
        unfiltered = _compute_stats(project_with_tags)
        assert filtered["distance_per_tag"] == unfiltered["distance_per_tag"]
