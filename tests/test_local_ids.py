"""Local ids and track fingerprints (issue #260, unit 2).

Both answer identity questions for activities the app creates itself, and they
answer different ones: the id says which row, the fingerprint says which
real-world track. Strava needs neither — its activity id is both.
"""
from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from models.project_db import DBActivity
from src.project.local_ids import (
    LocalIdExhausted,
    allocate_local_activity_id,
    track_fingerprint,
)

_TRACK = [(48.0, 2.0), (48.001, 2.001), (48.002, 2.002)]
_START = "2024-06-01T09:00:00+00:00"


@pytest.fixture
def sess():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


class TestAllocateLocalActivityId:
    def test_allocates_a_negative_id(self, sess):
        """Positive ids belong to Strava — a row's id IS its Strava id, which is
        what makes a sync's upsert idempotent."""
        assert allocate_local_activity_id(sess) < 0

    def test_successive_ids_differ(self, sess):
        ids = {allocate_local_activity_id(sess) for _ in range(20)}
        assert len(ids) == 20

    def test_avoids_an_id_already_taken(self, sess, monkeypatch):
        """The check is against the activity TABLE, not a project's timeline: a
        split tail whose item was removed leaves the row behind, and reusing its
        id would collide on INSERT."""
        import src.project.local_ids as local_ids

        taken = -42
        sess.add(DBActivity(id=taken, user_info_id=1, name="orphan", type="Ride"))
        sess.commit()

        draws = iter([-taken, -taken, 77])          # negated below, so -42, -42, -77
        monkeypatch.setattr(local_ids.secrets, "randbits", lambda _bits: next(draws))

        assert allocate_local_activity_id(sess) == -77

    def test_gives_up_rather_than_looping_forever(self, sess, monkeypatch):
        import src.project.local_ids as local_ids

        sess.add(DBActivity(id=-42, user_info_id=1, name="taken", type="Ride"))
        sess.commit()
        monkeypatch.setattr(local_ids.secrets, "randbits", lambda _bits: 42)

        with pytest.raises(LocalIdExhausted):
            allocate_local_activity_id(sess)

    def test_stays_inside_a_signed_64_bit_column(self, sess):
        for _ in range(50):
            assert allocate_local_activity_id(sess) > -(2 ** 63)


class TestTrackFingerprint:
    def test_the_same_track_fingerprints_the_same(self):
        assert track_fingerprint(_TRACK, _START) == track_fingerprint(_TRACK, _START)

    def test_different_geometry_fingerprints_differently(self):
        other = [(45.0, 6.0), (45.001, 6.001), (45.002, 6.002)]
        assert track_fingerprint(_TRACK, _START) != track_fingerprint(other, _START)

    def test_the_same_route_at_a_different_time_is_a_different_activity(self):
        """Two laps of the same loop, or the same commute on two days, are two
        activities — geometry alone would call them one."""
        assert track_fingerprint(_TRACK, _START) != track_fingerprint(
            _TRACK, "2024-06-02T09:00:00+00:00")

    def test_order_matters(self):
        assert track_fingerprint(_TRACK, _START) != track_fingerprint(
            list(reversed(_TRACK)), _START)

    def test_survives_a_float_round_trip(self):
        """The same file parsed twice must hash identically even if a coordinate
        comes back differing in its last bits."""
        jittered = [(lat + 1e-12, lng - 1e-12) for lat, lng in _TRACK]
        assert track_fingerprint(jittered, _START) == track_fingerprint(_TRACK, _START)

    def test_elevation_is_not_part_of_it(self):
        """Elevation is the part most likely to be rewritten after import — by
        an edit, or by the dropout repair in c4a9e1f70b38 — and a fingerprint
        that changed when the app corrected its own data would stop recognising
        the file it came from. The signature takes lat/lng pairs only, so this
        is a statement about the contract rather than a filter."""
        assert track_fingerprint(iter(_TRACK), _START) == track_fingerprint(_TRACK, _START)

    def test_a_track_with_no_start_time_still_fingerprints(self):
        assert track_fingerprint(_TRACK)
        assert track_fingerprint(_TRACK) != track_fingerprint(_TRACK, _START)
