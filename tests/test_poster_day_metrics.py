"""Tests for compute_day_metrics — per-day stats for poster memory cards (issue #14)."""

from datetime import datetime

import pytest

from src.models.encounter import Encounter
from src.models.project import Counter, CounterEntry, DayMeta, Project, ProjectItem
from src.poster.day_metrics import compute_day_metrics


def _encounter_item(date: str) -> ProjectItem:
    return ProjectItem(item_type="encounter", encounter=Encounter(date=date))


# ── Distance / elevation: all activity types, day-only ──────────────────────


class TestDistanceElevation:
    def test_sums_across_activity_types_on_target_date(self, make_activity):
        """Ride-only limitation is lifted: run/hike/etc. all count."""
        p = Project(name="t")
        p.activities = [
            make_activity(id=1, type="Ride", distance=30_000, total_elevation_gain=200,
                          start_date_local=datetime(2024, 6, 1, 8, 0)),
            make_activity(id=2, type="Run", distance=10_000, total_elevation_gain=50,
                          start_date_local=datetime(2024, 6, 1, 17, 0)),
            make_activity(id=3, type="Hike", distance=5_000, total_elevation_gain=300,
                          start_date_local=datetime(2024, 6, 1, 12, 0)),
        ]
        result = compute_day_metrics(p, "2024-06-01")
        assert result["distance_m"] == pytest.approx(45_000)
        assert result["elevation_m"] == pytest.approx(550)

    def test_excludes_other_days(self, make_activity):
        p = Project(name="t")
        p.activities = [
            make_activity(id=1, type="Run", distance=10_000, total_elevation_gain=50,
                          start_date_local=datetime(2024, 6, 1, 8, 0)),
            make_activity(id=2, type="Run", distance=99_000, total_elevation_gain=999,
                          start_date_local=datetime(2024, 6, 2, 8, 0)),
        ]
        result = compute_day_metrics(p, "2024-06-01")
        assert result["distance_m"] == pytest.approx(10_000)
        assert result["elevation_m"] == pytest.approx(50)

    def test_zero_on_day_with_no_activities(self, make_activity):
        p = Project(name="t")
        p.activities = [make_activity(id=1, start_date_local=datetime(2024, 6, 2, 8, 0))]
        result = compute_day_metrics(p, "2024-06-01")
        assert result["distance_m"] == 0.0
        assert result["elevation_m"] == 0.0


# ── Encounter count ──────────────────────────────────────────────────────────


class TestEncounterCount:
    def test_zero_encounters(self):
        p = Project(name="t")
        p.items = [_encounter_item("2024-06-02")]
        result = compute_day_metrics(p, "2024-06-01")
        assert result["encounter_count"] == 0

    def test_one_encounter(self):
        p = Project(name="t")
        p.items = [_encounter_item("2024-06-01")]
        result = compute_day_metrics(p, "2024-06-01")
        assert result["encounter_count"] == 1

    def test_multiple_encounters_same_day(self):
        p = Project(name="t")
        p.items = [
            _encounter_item("2024-06-01"),
            _encounter_item("2024-06-01"),
            _encounter_item("2024-06-02"),
        ]
        result = compute_day_metrics(p, "2024-06-01")
        assert result["encounter_count"] == 2


# ── Counters: cumulative as of target date ───────────────────────────────────


class TestCounters:
    def test_series_entry_exactly_on_target_date(self):
        p = Project(name="t")
        p.counters = [Counter(name="Coffee", start=0.0)]
        p.day_meta = {
            "2024-06-01": DayMeta(counters=[CounterEntry("Coffee", 3.0)]),
        }
        result = compute_day_metrics(p, "2024-06-01")
        assert result["counters"] == [{"name": "Coffee", "value": 3.0}]

    def test_target_date_between_two_entries_uses_earlier(self):
        p = Project(name="t")
        p.counters = [Counter(name="Coffee", start=0.0)]
        p.day_meta = {
            "2024-06-01": DayMeta(counters=[CounterEntry("Coffee", 3.0)]),
            "2024-06-05": DayMeta(counters=[CounterEntry("Coffee", 2.0)]),
        }
        result = compute_day_metrics(p, "2024-06-03")
        assert result["counters"] == [{"name": "Coffee", "value": 3.0}]

    def test_target_date_before_first_entry_uses_start(self):
        p = Project(name="t")
        p.counters = [Counter(name="Coffee", start=10.0)]
        p.day_meta = {
            "2024-06-05": DayMeta(counters=[CounterEntry("Coffee", 2.0)]),
        }
        result = compute_day_metrics(p, "2024-06-01")
        assert result["counters"] == [{"name": "Coffee", "value": 10.0}]


# ── Tag pie: cumulative distance-by-tag up to and including target date ──────


class TestTagPie:
    def test_only_includes_activities_up_to_target_date(self, make_activity):
        p = Project(name="t")
        p.day_meta = {
            "2024-06-01": DayMeta(tags=["Alps"]),
            "2024-06-02": DayMeta(tags=["Alps"]),
            "2024-06-03": DayMeta(tags=["Alps"]),
        }
        p.activities = [
            make_activity(id=1, type="Ride", distance=30_000,
                          start_date_local=datetime(2024, 6, 1, 8, 0)),
            make_activity(id=2, type="Ride", distance=20_000,
                          start_date_local=datetime(2024, 6, 2, 8, 0)),
            make_activity(id=3, type="Ride", distance=99_000,
                          start_date_local=datetime(2024, 6, 3, 8, 0)),
        ]
        result = compute_day_metrics(p, "2024-06-02")
        # 2024-06-03's 99k must be excluded — it's after the target date.
        assert result["tag_pie"] == {"Alps": pytest.approx(50_000)}

    def test_non_ride_activities_excluded(self, make_activity):
        p = Project(name="t")
        p.day_meta = {"2024-06-01": DayMeta(tags=["Stage"])}
        p.activities = [
            make_activity(id=1, type="Ride", distance=30_000,
                          start_date_local=datetime(2024, 6, 1, 8, 0)),
            make_activity(id=2, type="Run", distance=20_000,
                          start_date_local=datetime(2024, 6, 1, 8, 0)),
        ]
        result = compute_day_metrics(p, "2024-06-01")
        assert result["tag_pie"] == {"Stage": pytest.approx(30_000)}

    def test_empty_when_no_tags(self, make_activity):
        p = Project(name="t")
        p.day_meta = {"2024-06-01": DayMeta(tags=[])}
        p.activities = [
            make_activity(id=1, type="Ride", distance=30_000,
                          start_date_local=datetime(2024, 6, 1, 8, 0)),
        ]
        result = compute_day_metrics(p, "2024-06-01")
        assert result["tag_pie"] == {}
