"""Regression tests for issue #45 — "database is locked" on the track-save path.

Symptom: deleting a point inside an activity edit and saving would hang and fail
at a 30 s timeout. 30 s == SQLite ``busy_timeout`` (models/db.py), i.e. a writer
blocked on the single SQLite write lock for the full window before erroring.

Root cause (confirmed empirically, see the module docstring notes below):
every track mutation queues a background stats refresh
(``_refresh_stats_background`` → ``ProjectRepo.compute_and_cache_stats``) that
writes ``DBProject.stats_json``. A rapid delete→save→delete→save burst stacked
one such writer per save. On SQLite only one connection may write at a time, so
those stats-commits serialise behind each other *and* behind the next save's own
``edit_activity_track`` commit via busy_timeout — under a burst a save could wait
the full 30 s and raise ``OperationalError: database is locked``. (The sibling
tile refresh already coalesces at the render layer and never touches the DB, so
the stats writer was the only stacked DB writer.)

Notes on reproduction fidelity:
  * A FILE-backed SQLite engine with a real second connection is required — an
    in-memory ``StaticPool`` engine shares one connection and can never surface a
    cross-connection lock. We mirror production pragmas (WAL + synchronous=NORMAL)
    but use a SHORT busy_timeout so a genuine lock fails in ms, not 30 s.
  * pysqlite does not hold a read snapshot across ``SELECT`` statements, so the
    contention is plain writer-vs-writer, not a read→write snapshot upgrade.

Fix: ``_refresh_stats_background`` coalesces per project — at most one stats
writer runs at a time; refreshes requested while one is in flight set a rerun
flag so the final state is still recomputed exactly once.

Follow-up (same symptom, different trigger): coalescing bounds *concurrent*
writers to one, but doesn't bound how long a single commit can hold the write
lock. SQLite's default WAL behaviour runs an inline checkpoint synchronously
inside whichever commit crosses the ~1000-page threshold — on slow storage
(e.g. NAS disks) that checkpoint I/O can itself take seconds, and any other
writer queued behind it burns its busy_timeout waiting on that one unlucky
commit. Fix: disable the inline auto-checkpoint (``wal_autocheckpoint=0``) and
replace it with a periodic PASSIVE checkpoint (``models.db.checkpoint_wal``)
that never blocks a concurrent writer.
"""
from __future__ import annotations

import json
import threading
import time

import polyline as polyline_lib
import pytest
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine, select

import api.project_shared as shared_module
import models.db as db_module
from models.project_db import DBActivity, DBProject, DBProjectItem
from models.user import UserInfo
from src.project.project_repo import ProjectRepo

_TRACK = [(48.0, 2.0), (48.0, 2.01), (48.0, 2.02), (48.0, 2.03), (48.0, 2.04)]
_ELEV = [100.0, 120.0, 110.0, 140.0, 130.0]


def _make_file_engine(tmp_path, busy_timeout_ms: int = 300):
    """A file-backed SQLite engine matching production pragmas, but with a short
    busy_timeout so a genuine lock fails fast instead of hanging for 30 s."""
    db = tmp_path / "lock.db"
    eng = create_engine(
        f"sqlite:///{db}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(eng, "connect")
    def _pragmas(dbapi_conn, _rec):  # noqa: ANN001
        cur = dbapi_conn.cursor()
        try:
            cur.execute(f"PRAGMA busy_timeout={busy_timeout_ms}")
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA wal_autocheckpoint=0")
        finally:
            cur.close()

    SQLModel.metadata.create_all(eng)
    return eng


def _seed(engine) -> int:
    with Session(engine) as sess:
        u = UserInfo(display_name="A", email="a@e.com")
        sess.add(u); sess.commit(); sess.refresh(u)
        proj = DBProject(user_info_id=u.id, name="My Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)

        poly = polyline_lib.encode(_TRACK)
        dist_km = [i * 1.0 for i in range(len(_TRACK))]
        act = DBActivity(
            id=111, user_info_id=u.id, name="Ride", type="Ride",
            distance=4000.0, moving_time=1000, elapsed_time=1200,
            total_elevation_gain=60.0, summary_polyline=poly,
            elevation_profile_json=json.dumps(
                {"distances_km": dist_km, "elevations_m": _ELEV}),
            start_latlng_json=json.dumps([48.0, 2.0]),
            end_latlng_json=json.dumps([48.0, 2.04]),
        )
        sess.add(act)
        sess.add(DBProjectItem(project_id=proj.id, position=0,
                               item_type="activity", activity_id=111))
        sess.commit()
        return u.id


@pytest.fixture
def env(tmp_path, monkeypatch):
    engine = _make_file_engine(tmp_path)
    monkeypatch.setattr(db_module, "engine", engine)
    # Isolate the module-level coalescing state between tests.
    monkeypatch.setattr(shared_module, "_stats_refresh_state", {})
    uid = _seed(engine)
    return engine, uid


def test_direct_writer_contention_reproduces_lock(env):
    """Characterisation: with a short busy_timeout, a save whose write lock is held
    by another open write transaction gets ``database is locked`` — the raw
    mechanism behind the 30 s hang (busy_timeout == 30000 in production). This is
    exactly what stacked background stats writers used to inflict on the save."""
    engine, _uid = env
    repo = ProjectRepo()
    from src.models.track_edit import TrackPoint
    tps = [TrackPoint(lat=la, lng=lo, elev=None)
           for la, lo in [(48.0, 2.0), (48.0, 2.01), (48.0, 2.02)]]

    holder = engine.raw_connection()
    try:
        cur = holder.cursor()
        cur.execute("BEGIN IMMEDIATE")  # acquire and hold the write lock
        cur.execute("UPDATE project SET updated_at = 1 WHERE id = 1")

        with Session(engine) as sess:
            with pytest.raises(OperationalError, match="database is locked"):
                repo.edit_activity_track(sess, 111, tps)
    finally:
        holder.rollback()
        holder.close()


def test_burst_saves_coalesce_stats_refresh(env, monkeypatch):
    """Fix: a burst of saves for one project must NOT stack concurrent stats
    writers. While one refresh is in flight, further requests coalesce into a
    single rerun instead of each spawning another concurrent SQLite writer.

    Before the fix ``_refresh_stats_background`` recomputed once per call
    (N calls → N concurrent writers → lock contention); after it, N calls while
    one is running collapse to exactly two recomputes: the initial run plus one
    trailing rerun that captures the latest state.
    """
    engine, uid = env
    calls: list[int] = []
    started = threading.Event()
    release = threading.Event()

    def fake_compute(sess, u, n):
        calls.append(1)
        if len(calls) == 1:
            started.set()        # first refresh is now running
            release.wait(3)      # hold it so the burst piles up while it runs

    monkeypatch.setattr(shared_module._repo, "compute_and_cache_stats", fake_compute)

    worker = threading.Thread(
        target=shared_module._refresh_stats_background, args=(uid, "My Trip"))
    worker.start()
    assert started.wait(3), "first refresh never started"

    # Burst of five more saves arriving while the first refresh is still running.
    for _ in range(5):
        shared_module._refresh_stats_background(uid, "My Trip")

    release.set()
    worker.join(5)
    assert not worker.is_alive()

    # Exactly one initial run + one coalesced rerun — not six concurrent writers.
    assert len(calls) == 2


def test_coalesced_refresh_persists_stats(env):
    """A single coalesced refresh still recomputes and caches real stats."""
    engine, uid = env
    shared_module._refresh_stats_background(uid, "My Trip")
    with Session(engine) as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == uid, DBProject.name == "My Trip")
        ).first()
        assert row.stats_json is not None
        assert json.loads(row.stats_json)  # non-empty stats dict


def test_wal_autocheckpoint_disabled(env):
    """Automatic checkpointing must be off — otherwise whichever commit crosses
    the WAL size threshold pays the checkpoint's I/O cost inline and holds the
    single write lock for its duration, exactly like the stacked-writer issue
    but triggered by any commit instead of a burst."""
    engine, _uid = env
    with engine.connect() as conn:
        value = conn.exec_driver_sql("PRAGMA wal_autocheckpoint").scalar()
    assert value == 0


def test_checkpoint_wal_does_not_block_concurrent_writer(env):
    """A PASSIVE checkpoint must never make an interactive writer wait: while
    another connection holds an open write transaction, checkpoint_wal() should
    return promptly (checkpointing fewer frames, not blocking) instead of
    contending for the lock itself."""
    engine, _uid = env

    holder = engine.raw_connection()
    try:
        cur = holder.cursor()
        cur.execute("BEGIN IMMEDIATE")  # acquire and hold the write lock
        cur.execute("UPDATE project SET updated_at = 2 WHERE id = 1")

        start = time.monotonic()
        db_module.checkpoint_wal()  # must not raise or hang behind the lock
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
    finally:
        holder.rollback()
        holder.close()
