"""Durable route jobs and startup recovery (issue #173, phase D).

Before this, the only record that a resolve was owed was
``route_status="pending"`` on the segment, and the only thing that noticed a
lost job was the *Flutter client* — five minutes stale, and only if someone
reopened the project. A server-side crash was recovered by the client, or not
at all.

A ``DBRouteJob`` row now records the intent, and a startup sweep re-queues
anything left non-terminal.
"""
from __future__ import annotations

import json

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import models.db as db_module
import src.jobs.route_jobs as route_jobs
from models.project_db import DBProject, DBProjectItem, DBRouteJob
from models.user import UserInfo
from src.jobs.route_jobs import (
    MAX_ATTEMPTS,
    MAX_DEGRADE_RETRIES,
    create_job,
    mark_done,
    mark_failed,
    mark_running,
    sweep_degraded_segments,
    sweep_orphaned_jobs,
)


# The trigger always stamps route_started_at alongside route_status="pending";
# the job carries it back as its token. Fixtures must match or the guard
# correctly refuses every write.
TOKEN = "2026-07-30T10:00:00Z"


@pytest.fixture
def env(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as sess:
        user = UserInfo(display_name="A", email="a@e.com")
        sess.add(user); sess.commit(); sess.refresh(user)
        proj = DBProject(user_info_id=user.id, name="Trip")
        sess.add(proj); sess.commit(); sess.refresh(proj)
        sess.add(DBProjectItem(
            project_id=proj.id, position=0, item_type="segment",
            uid="u1", segment_id="seg-1",
            segment_json=json.dumps({"id": "seg-1", "segment_type": "boat",
                                     "route_status": "pending",
                                     "route_started_at": TOKEN}),
        ))
        sess.commit()
        return engine, user.id, proj.id


def _jobs(engine):
    with Session(engine) as sess:
        return sess.exec(select(DBRouteJob).order_by(DBRouteJob.id)).all()


class TestJobLifecycle:
    def test_a_job_is_recorded_pending(self, env):
        engine, user_id, project_id = env
        job_id = create_job(user_id, project_id, "Trip", "seg-1", "2026-07-30T10:00:00Z",
                            {"hafas_provider": "vr"})

        jobs = _jobs(engine)
        assert len(jobs) == 1
        assert jobs[0].id == job_id
        assert jobs[0].status == "pending"
        assert jobs[0].segment_id == "seg-1"
        assert jobs[0].started_at == "2026-07-30T10:00:00Z"
        assert json.loads(jobs[0].params_json) == {"hafas_provider": "vr"}

    def test_status_transitions_are_recorded(self, env):
        engine, user_id, project_id = env
        job_id = create_job(user_id, project_id, "Trip", "seg-1", "t", {})

        mark_running(job_id)
        assert _jobs(engine)[0].status == "running"

        mark_done(job_id)
        done = _jobs(engine)[0]
        assert done.status == "done"
        assert done.completed_at is not None

    def test_failure_records_the_message(self, env):
        engine, user_id, project_id = env
        job_id = create_job(user_id, project_id, "Trip", "seg-1", "t", {})
        mark_failed(job_id, "overpass exploded")

        failed = _jobs(engine)[0]
        assert failed.status == "failed"
        assert "overpass exploded" in failed.error_message

    def test_a_new_request_supersedes_the_previous_job(self, env):
        """Otherwise the sweep would re-queue a job whose verdict is discarded."""
        engine, user_id, project_id = env
        first = create_job(user_id, project_id, "Trip", "seg-1", "t1", {})
        second = create_job(user_id, project_id, "Trip", "seg-1", "t2", {})

        by_id = {j.id: j for j in _jobs(engine)}
        assert by_id[first].status == "failed"
        assert "superseded" in by_id[first].error_message
        assert by_id[second].status == "pending"

    def test_bookkeeping_never_raises_on_a_missing_job(self, env):
        """A lost row must not take the resolve down with it."""
        mark_running(999999)
        mark_done(999999)
        mark_failed(999999, "x")
        mark_running(None)   # the no-job-row path (direct calls, older enqueues)


class TestStartupSweep:
    def test_a_pending_job_is_requeued(self, env, monkeypatch):
        engine, user_id, project_id = env
        job_id = create_job(user_id, project_id, "Trip", "seg-1", "t",
                            {"hafas_provider": "vr"})

        enqueued: list = []
        monkeypatch.setattr(route_jobs, "_resolve_route_job", lambda *a, **k: None,
                            raising=False)
        import src.jobs.queue as queue_mod
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append((q, a)) or True)

        assert sweep_orphaned_jobs() == 1
        assert len(enqueued) == 1
        _queue, args = enqueued[0]
        assert args[:3] == (user_id, "Trip", "seg-1")
        assert args[3] == {"hafas_provider": "vr"}
        assert args[5] == job_id

    def test_a_running_job_is_requeued_too(self, env, monkeypatch):
        """At startup nothing is executing, so "running" means "died mid-run"."""
        engine, user_id, project_id = env
        job_id = create_job(user_id, project_id, "Trip", "seg-1", "t", {})
        mark_running(job_id)

        import src.jobs.queue as queue_mod
        enqueued: list = []
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append(a) or True)

        assert sweep_orphaned_jobs() == 1

    def test_terminal_jobs_are_left_alone(self, env, monkeypatch):
        engine, user_id, project_id = env
        mark_done(create_job(user_id, project_id, "Trip", "seg-1", "t", {}))

        import src.jobs.queue as queue_mod
        enqueued: list = []
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append(a) or True)

        assert sweep_orphaned_jobs() == 0
        assert enqueued == []

    def test_a_job_that_keeps_dying_is_abandoned_not_looped(self, env, monkeypatch):
        """A poison job would otherwise take a worker down on every boot."""
        engine, user_id, project_id = env
        job_id = create_job(user_id, project_id, "Trip", "seg-1", "t", {})

        import src.jobs.queue as queue_mod
        monkeypatch.setattr(queue_mod, "enqueue", lambda q, f, *a, **k: True)

        for _ in range(MAX_ATTEMPTS + 2):
            sweep_orphaned_jobs()

        final = _jobs(engine)[0]
        assert final.status == "failed"
        assert "abandoned" in final.error_message

    def test_an_abandoned_job_unsticks_its_segment(self, env, monkeypatch):
        """The tile must stop spinning even when we give up on the job."""
        engine, user_id, project_id = env
        create_job(user_id, project_id, "Trip", "seg-1", TOKEN, {})

        import src.jobs.queue as queue_mod
        monkeypatch.setattr(queue_mod, "enqueue", lambda q, f, *a, **k: True)
        for _ in range(MAX_ATTEMPTS + 2):
            sweep_orphaned_jobs()

        with Session(engine) as sess:
            row = sess.exec(select(DBProjectItem).where(
                DBProjectItem.segment_id == "seg-1")).first()
        seg = json.loads(row.segment_json)
        assert seg["route_status"] == "failed"
        assert "restart" in (seg["route_error"] or "")

    def test_a_broken_sweep_does_not_stop_the_app_booting(self, env, monkeypatch):
        def _boom(*_a, **_kw):
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(route_jobs, "get_session", _boom)
        assert sweep_orphaned_jobs() == 0   # logged, not raised


def _degraded_segment(**overrides):
    seg = {
        "id": "seg-1", "segment_type": "train",
        "route_status": "resolved", "route_degraded": True,
        "route_degrade_retries": 0,
        "hafas_provider": "db", "train_number": "ICE 596",
        "date": "2026-08-01",
    }
    seg.update(overrides)
    return seg


@pytest.fixture
def degraded_env(monkeypatch):
    """One project with one segment whose shape a test customises via [seg]."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)

    def _seed(seg: dict):
        with Session(engine) as sess:
            user = UserInfo(display_name="A", email="a@e.com")
            sess.add(user); sess.commit(); sess.refresh(user)
            proj = DBProject(user_info_id=user.id, name="Trip")
            sess.add(proj); sess.commit(); sess.refresh(proj)
            sess.add(DBProjectItem(
                project_id=proj.id, position=0, item_type="segment",
                uid="u1", segment_id="seg-1", segment_json=json.dumps(seg),
            ))
            sess.commit()
            return engine, user.id, proj.id

    return _seed


def _segment_row(engine):
    with Session(engine) as sess:
        return sess.exec(select(DBProjectItem).where(
            DBProjectItem.segment_id == "seg-1")).first()


class TestDegradedSegmentSweep:
    def test_a_degraded_segment_is_retried(self, degraded_env, monkeypatch):
        engine, user_id, project_id = degraded_env(_degraded_segment())

        enqueued: list = []
        import src.jobs.queue as queue_mod
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append(a) or True)

        assert sweep_degraded_segments() == 1
        assert len(enqueued) == 1
        user_arg, name_arg, seg_id_arg, params, _started_at, _job_id = enqueued[0]
        assert (user_arg, name_arg, seg_id_arg) == (user_id, "Trip", "seg-1")
        assert params == {
            "hafas_provider": "db", "train_number": "ICE 596", "date": "2026-08-01",
        }

        row = _segment_row(engine)
        seg = json.loads(row.segment_json)
        assert seg["route_status"] == "pending"
        assert seg["route_degrade_retries"] == 1

    def test_a_fully_resolved_segment_is_left_alone(self, degraded_env, monkeypatch):
        engine, _user_id, _project_id = degraded_env(
            _degraded_segment(route_degraded=False))

        import src.jobs.queue as queue_mod
        enqueued: list = []
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append(a) or True)

        assert sweep_degraded_segments() == 0
        assert enqueued == []

    def test_a_pending_segment_is_not_retried(self, degraded_env, monkeypatch):
        """route_degraded=True with route_status="pending" shouldn't occur in
        practice (a fresh resolve always clears route_degraded first), but the
        sweep must not double-trigger an already in-flight resolve either way."""
        degraded_env(_degraded_segment(route_status="pending"))

        import src.jobs.queue as queue_mod
        enqueued: list = []
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append(a) or True)

        assert sweep_degraded_segments() == 0
        assert enqueued == []

    def test_exhausted_retries_stop_being_retried(self, degraded_env, monkeypatch):
        degraded_env(_degraded_segment(route_degrade_retries=MAX_DEGRADE_RETRIES))

        import src.jobs.queue as queue_mod
        enqueued: list = []
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append(a) or True)

        assert sweep_degraded_segments() == 0
        assert enqueued == []

    def test_a_broken_sweep_does_not_raise(self, degraded_env, monkeypatch):
        degraded_env(_degraded_segment())

        def _boom(*_a, **_kw):
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(route_jobs, "get_session", _boom)
        assert sweep_degraded_segments() == 0
