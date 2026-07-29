"""How long a trip is, in days (issue #121).

The rule under test: a trip's length is its calendar span, first day to last,
**including the days with nothing on them**. A ride with a rest week in the
middle is not shorter for it.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.project_db import (
    DBActivity,
    DBJournalEntry,
    DBMemory,
    DBProject,
    DBProjectItem,
)
from models.user import UserInfo
from src.billing.trip_days import (
    bounds,
    normalise,
    project_day_bounds,
    span_days,
    span_of,
)


# ── Pure arithmetic ───────────────────────────────────────────────────────────

class TestNormalise:
    def test_a_plain_date_passes_through(self):
        assert normalise("2026-06-01") == "2026-06-01"

    def test_an_iso_datetime_is_cut_to_its_date(self):
        assert normalise("2026-06-01T09:30:00Z") == "2026-06-01"

    def test_junk_is_dropped_rather_than_guessed_at(self):
        """A bad row must not silently stretch someone's trip."""
        assert normalise("not a date") is None
        assert normalise("2026-13-45") is None

    def test_empty_values_are_dropped(self):
        assert normalise(None) is None
        assert normalise("") is None


class TestSpan:
    def test_a_single_day_is_one_day(self):
        assert span_days("2026-06-01", "2026-06-01") == 1

    def test_the_span_is_inclusive_of_both_ends(self):
        assert span_days("2026-06-01", "2026-06-10") == 10

    def test_empty_days_in_the_middle_still_count(self):
        """Content on day 1 and day 21 is a 21-day trip, not a 2-day one."""
        assert span_of(["2026-06-01", "2026-06-21"]) == 21

    def test_an_unknown_end_is_no_span(self):
        assert span_days("2026-06-01", None) == 0
        assert span_days(None, None) == 0

    def test_order_does_not_matter(self):
        assert span_of(["2026-06-21", "2026-06-01", "2026-06-10"]) == 21

    def test_a_leap_day_counts(self):
        assert span_days("2028-02-28", "2028-03-01") == 3

    def test_unparseable_dates_are_ignored(self):
        assert span_of(["2026-06-01", "nonsense", "2026-06-05"]) == 5

    def test_no_dates_at_all(self):
        assert span_of([]) == 0
        assert bounds([]) == (None, None)


# ── Bounds from a real project ────────────────────────────────────────────────

@pytest.fixture
def sess():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(UserInfo(id=1, email="a@example.com", display_name="A"))
        session.add(DBProject(id=1, user_info_id=1, name="Trip"))
        session.commit()
        yield session


def _memory(sess, date):
    sess.add(DBMemory(project_id=1, date=date, geo_mode="custom",
                      photos_json="[]"))
    sess.commit()


def _journal(sess, date):
    sess.add(DBJournalEntry(project_id=1, user_info_id=1, date=date,
                            photos_json="[]", geo_mode="custom"))
    sess.commit()


def _activity(sess, start_local, activity_id=None):
    row = DBActivity(user_info_id=1, name="Ride", type="Ride",
                     start_date_local=start_local)
    if activity_id is not None:
        row.id = activity_id
    sess.add(row)
    sess.commit()
    sess.refresh(row)
    sess.add(DBProjectItem(project_id=1, position=0, item_type="activity",
                           activity_id=row.id))
    sess.commit()


def _segment(sess, date):
    sess.add(DBProjectItem(project_id=1, position=0, item_type="segment",
                           segment_json=json.dumps({"id": "s1", "date": date})))
    sess.commit()


class TestProjectDayBounds:
    def test_an_empty_trip_has_no_bounds(self, sess):
        assert project_day_bounds(sess, 1) == (None, None)

    def test_memories_set_the_bounds(self, sess):
        _memory(sess, "2026-06-05")
        _memory(sess, "2026-06-01")
        assert project_day_bounds(sess, 1) == ("2026-06-01", "2026-06-05")

    def test_journals_count(self, sess):
        _memory(sess, "2026-06-05")
        _journal(sess, "2026-06-09")
        assert project_day_bounds(sess, 1)[1] == "2026-06-09"

    def test_activities_count_and_their_time_is_dropped(self, sess):
        _activity(sess, "2026-06-02T08:00:00")
        _activity(sess, "2026-06-04T19:30:00")
        assert project_day_bounds(sess, 1) == ("2026-06-02", "2026-06-04")

    def test_segments_count(self, sess):
        _memory(sess, "2026-06-05")
        _segment(sess, "2026-06-12")
        assert project_day_bounds(sess, 1)[1] == "2026-06-12"

    def test_a_segment_with_no_date_is_skipped(self, sess):
        _memory(sess, "2026-06-05")
        sess.add(DBProjectItem(project_id=1, position=1, item_type="segment",
                               segment_json=json.dumps({"id": "s2"})))
        sess.commit()
        assert project_day_bounds(sess, 1) == ("2026-06-05", "2026-06-05")

    def test_malformed_segment_json_does_not_break_the_count(self, sess):
        _memory(sess, "2026-06-05")
        sess.add(DBProjectItem(project_id=1, position=1, item_type="segment",
                               segment_json="{not json"))
        sess.commit()
        assert project_day_bounds(sess, 1) == ("2026-06-05", "2026-06-05")

    def test_declared_trip_dates_widen_the_span(self, sess):
        """A trip declared to start earlier than its first activity is that long
        — the empty lead-in days are days of the trip."""
        _memory(sess, "2026-06-10")
        project = sess.get(DBProject, 1)
        project.trip_start = "2026-06-01"
        sess.add(project)
        sess.commit()
        assert project_day_bounds(sess, 1) == ("2026-06-01", "2026-06-10")

    def test_another_project_does_not_leak_in(self, sess):
        sess.add(DBProject(id=2, user_info_id=1, name="Other"))
        sess.commit()
        sess.add(DBMemory(project_id=2, date="2030-01-01", geo_mode="custom",
                          photos_json="[]"))
        sess.commit()
        _memory(sess, "2026-06-05")
        assert project_day_bounds(sess, 1) == ("2026-06-05", "2026-06-05")
