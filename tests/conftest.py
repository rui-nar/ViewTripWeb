"""Shared fixtures for all test modules."""

from datetime import datetime
import pytest

from prometheus_client import REGISTRY

from src.models.activity import Activity


@pytest.fixture(autouse=True)
def _reset_strava_rate_limiters():
    """Clear the process-wide Strava quota windows around every test.

    The limiters are shared by design (issue #130 — Strava's quota is per
    application), which means one test's mocked calls otherwise count against
    the next one's, and a suite making 100+ calls would start really sleeping.
    """
    from src.api.strava_client import reset_rate_limiters

    reset_rate_limiters()
    yield
    reset_rate_limiters()


@pytest.fixture
def metric():
    """Read a Prometheus sample by name + labels, 0.0 if the series is absent.

    The default registry is process-wide and counters only ever increase, so
    tests must assert on the *delta* around the code under test — never on an
    absolute value, which depends on whatever else ran earlier in the session.
    """
    def _read(name: str, **labels) -> float:
        return REGISTRY.get_sample_value(name, labels or None) or 0.0
    return _read


@pytest.fixture
def make_activity():
    """Factory fixture — call with keyword overrides to customise any field."""
    def _make(**kwargs):
        defaults = dict(
            id=1,
            name="Morning Run",
            type="Run",
            distance=10000.0,
            moving_time=3600,
            elapsed_time=3660,
            total_elevation_gain=100.0,
            start_date=datetime(2024, 6, 15, 7, 0),
            start_date_local=datetime(2024, 6, 15, 9, 0),
            timezone="Europe/Paris",
            achievement_count=2,
            kudos_count=5,
            comment_count=1,
            athlete_count=1,
            photo_count=0,
            trainer=False,
            commute=False,
            manual=False,
            private=False,
            flagged=False,
            average_speed=2.78,   # m/s ≈ 10 km/h
            max_speed=3.5,
            has_heartrate=False,
            pr_count=0,
            total_photo_count=0,
            has_kudoed=False,
        )
        defaults.update(kwargs)
        return Activity(**defaults)
    return _make
