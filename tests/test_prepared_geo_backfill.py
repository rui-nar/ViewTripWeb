"""The backfill sweep for prepared activity geometry — issue #369 stage B2.

Activities written since #369 get their prepared blob beside the polyline. Ones
that predate it have no row and would otherwise be prepared lazily on a user's
first open of the trip — correct, but it means the first open still pays the
cost the change exists to remove. This sweep drains that backlog in the
background.

What these pin is that it is *bounded*, *terminates*, *skips what it cannot
prepare*, and — the one that matters most — that it cannot overwrite a writer
that landed while it was preparing.
"""
from __future__ import annotations

import json

import polyline as polyline_lib
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
import src.jobs.prepared_geo_jobs as jobs
from models.project_db import DBActivity, DBActivityGeoPrepared
from src.models.prepared_geo import unpack_prepared_line
from src.models.simplify import PREPARED_GEO_VERSION


def _track(seed: int, n: int = 60):
    return [(45.0 + seed * 0.01 + i * 0.0001, 7.0 + i * 0.0001) for i in range(n)]


def _encoded(seed: int, n: int = 60) -> str:
    return polyline_lib.encode(_track(seed, n))


@pytest.fixture
def db(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(db_module, "engine", engine)
    # The job module binds the engine at import time.
    monkeypatch.setattr(jobs, "engine", engine)
    return engine


def _add(engine, activity_id: int, polyline: str | None):
    with Session(engine) as sess:
        sess.add(DBActivity(
            id=activity_id, user_info_id=1, name=f"A{activity_id}", type="Ride",
            start_date="2026-06-01T00:00:00Z", summary_polyline=polyline,
            start_latlng_json=json.dumps([45.0, 7.0]),
        ))
        sess.commit()


def _rows(engine) -> dict[int, DBActivityGeoPrepared]:
    with Session(engine) as sess:
        return {r.activity_id: r for r in sess.exec(select(DBActivityGeoPrepared)).all()}


def test_it_prepares_activities_that_have_no_row(db):
    for i in range(3):
        _add(db, 100 + i, _encoded(i))

    assert jobs.sweep_unprepared_geometry() == 3
    rows = _rows(db)
    assert set(rows) == {100, 101, 102}
    assert all(r.version == PREPARED_GEO_VERSION for r in rows.values())
    # A real blob, not a placeholder.
    points, levels, _bbox, version = unpack_prepared_line(rows[100].blob)
    assert version == PREPARED_GEO_VERSION
    assert len(levels) == len(points) // 2


def test_it_is_bounded_per_run_and_terminates(db):
    for i in range(7):
        _add(db, 200 + i, _encoded(i))

    assert jobs.sweep_unprepared_geometry(limit=3) == 3
    assert jobs.sweep_unprepared_geometry(limit=3) == 3
    assert jobs.sweep_unprepared_geometry(limit=3) == 1
    # Drained: further runs are no-ops, which is what lets this sit on a
    # five-minute schedule forever.
    assert jobs.sweep_unprepared_geometry(limit=3) == 0


def test_a_second_run_does_not_redo_the_first(db):
    _add(db, 300, _encoded(1))
    assert jobs.sweep_unprepared_geometry() == 1
    before = _rows(db)[300].blob
    assert jobs.sweep_unprepared_geometry() == 0
    assert _rows(db)[300].blob == before


def test_it_skips_an_encrypted_polyline(db):
    """The server holds no key, so there is nothing to prepare — and a row would
    be worse than none: the reader would serve it."""
    _add(db, 400, "v1.YWJj.ZGVm")
    _add(db, 401, _encoded(2))
    assert jobs.sweep_unprepared_geometry() == 1
    assert set(_rows(db)) == {401}


def test_it_skips_an_activity_with_no_polyline(db):
    _add(db, 500, None)
    assert jobs.sweep_unprepared_geometry() == 0
    assert _rows(db) == {}


def test_one_undecodable_row_does_not_cost_the_batch(db):
    _add(db, 600, "!!!not a polyline!!!")
    _add(db, 601, _encoded(3))
    # The bad row is logged and skipped; the good one is still prepared.
    assert jobs.sweep_unprepared_geometry() == 1
    assert set(_rows(db)) == {601}


def test_a_stale_version_row_is_refreshed(db):
    _add(db, 700, _encoded(4))
    with Session(db) as sess:
        sess.add(DBActivityGeoPrepared(
            activity_id=700, version=PREPARED_GEO_VERSION - 1, blob=b"stale"))
        sess.commit()

    assert jobs.sweep_unprepared_geometry() == 1
    row = _rows(db)[700]
    assert row.version == PREPARED_GEO_VERSION
    assert row.blob != b"stale"


def test_it_cannot_overwrite_a_write_that_landed_while_it_prepared(db, monkeypatch):
    """The race the read path was caught by, in the sweep's own shape.

    Preparation happens outside any transaction, so a writer can change the
    polyline in between. Without the compare-and-swap the sweep would store
    geometry built from the *old* value at the current version — indistinguishable
    from fresh, and served until the next polyline write.
    """
    _add(db, 800, _encoded(5))
    real_prepare = jobs.prepare_polyline

    def prepare_then_let_a_writer_in(polyline):
        blob = real_prepare(polyline)
        with Session(db) as sess:
            row = sess.get(DBActivity, 800)
            row.summary_polyline = _encoded(99)
            sess.add(row)
            sess.commit()
        return blob

    monkeypatch.setattr(jobs, "prepare_polyline", prepare_then_let_a_writer_in)

    jobs.sweep_unprepared_geometry()
    # The guard refused the write, so no row was left claiming to be current for
    # geometry that is no longer the activity's.
    assert _rows(db) == {}

    # And the next sweep, seeing the new polyline, prepares it correctly.
    monkeypatch.setattr(jobs, "prepare_polyline", real_prepare)
    assert jobs.sweep_unprepared_geometry() == 1
    assert _rows(db)[800].version == PREPARED_GEO_VERSION
