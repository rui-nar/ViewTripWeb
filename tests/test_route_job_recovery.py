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
    MAX_STALE_RESOLVES_PER_SWEEP,
    RESOLVER_VERSION,
    create_job,
    mark_done,
    mark_failed,
    mark_running,
    sweep_degraded_segments,
    sweep_orphaned_jobs,
    sweep_stale_resolver_segments,
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

    # A train whose schedule lookup failed resolves via the generic two-point
    # OSM fallback: route_status="resolved", route_degraded=False (OSM found
    # *a* track), route_hafas_failed=True. That used to be invisible to the
    # sweep, so a route that isn't the user's train stuck forever (issue #277).

    def test_a_hafas_fallback_segment_is_retried(self, degraded_env, monkeypatch):
        engine, user_id, _project_id = degraded_env(_degraded_segment(
            route_degraded=False, route_hafas_failed=True))

        import src.jobs.queue as queue_mod
        enqueued: list = []
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append(a) or True)

        assert sweep_degraded_segments() == 1
        assert len(enqueued) == 1
        user_arg, name_arg, seg_id_arg, _params, _started_at, _job_id = enqueued[0]
        assert (user_arg, name_arg, seg_id_arg) == (user_id, "Trip", "seg-1")

        seg = json.loads(_segment_row(engine).segment_json)
        assert seg["route_status"] == "pending"
        # Shares the degraded retry budget — no parallel counter.
        assert seg["route_degrade_retries"] == 1

    def test_an_exhausted_hafas_fallback_stops_being_retried(
            self, degraded_env, monkeypatch):
        degraded_env(_degraded_segment(
            route_degraded=False, route_hafas_failed=True,
            route_degrade_retries=MAX_DEGRADE_RETRIES))

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


class TestTheDegradedRetryBudgetActuallyTerminates:
    """The sweep and the resolve it queues must agree on the retry counter.

    Every test above seeds ``route_degrade_retries`` directly, so all of them
    passed while the two halves disagreed: the sweep incremented the counter,
    and the resolve it queued reset it to 0 because a degraded result is still
    ``route_status="resolved"``. MAX_DEGRADE_RETRIES was therefore unreachable
    and every degraded segment was re-resolved hourly, forever — observed in
    production on 2026-09-06, where each pass also flipped a usable approximate
    route back to a spinner for the several minutes the retry took.

    These drive the real round trip instead of seeding the counter.
    """

    @staticmethod
    def _run_sweep_and_resolve(engine, monkeypatch, *, degraded, hafas_failed=False):
        """One full cycle: sweep marks pending, the queued job writes a verdict."""
        import api.segments as segments_mod
        import src.jobs.queue as queue_mod

        enqueued: list = []
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append((f, a)) or True)
        monkeypatch.setattr(segments_mod, "bust_geo_cache", lambda *a, **k: None)
        monkeypatch.setattr(segments_mod, "warm_geo_cache", lambda *a, **k: None)
        monkeypatch.setattr(segments_mod, "warm_meta_cache", lambda *a, **k: None)

        def _geometry(seg, _params):
            seg.route_hafas_failed = hafas_failed
            return [[0.0, 0.0], [1.0, 1.0]], 2, degraded, "straight"

        monkeypatch.setattr(segments_mod, "_compute_segment_geometry", _geometry)

        swept = sweep_degraded_segments()
        for func, args in enqueued:
            func(*args)
        return swept

    def test_repeated_degraded_results_exhaust_the_budget(
            self, degraded_env, monkeypatch):
        engine, _user_id, _project_id = degraded_env(_degraded_segment())

        cycles = 0
        for _ in range(MAX_DEGRADE_RETRIES + 5):
            if not self._run_sweep_and_resolve(engine, monkeypatch, degraded=True):
                break
            cycles += 1

        assert cycles == MAX_DEGRADE_RETRIES, (
            "the sweep must stop retrying a segment that keeps coming back "
            "degraded — it ran %d times" % cycles)
        seg = json.loads(_segment_row(engine).segment_json)
        assert seg["route_degrade_retries"] == MAX_DEGRADE_RETRIES
        assert seg["route_status"] == "resolved"

    def test_a_hafas_fallback_result_also_exhausts_the_budget(
            self, degraded_env, monkeypatch):
        """The same trap via the other provisional outcome: OSM found a track,
        but not for the train the user asked for."""
        engine, _user_id, _project_id = degraded_env(
            _degraded_segment(route_degraded=False, route_hafas_failed=True))

        cycles = 0
        for _ in range(MAX_DEGRADE_RETRIES + 5):
            if not self._run_sweep_and_resolve(
                    engine, monkeypatch, degraded=False, hafas_failed=True):
                break
            cycles += 1

        assert cycles == MAX_DEGRADE_RETRIES

    def test_a_real_route_restarts_the_budget(self, degraded_env, monkeypatch):
        """The behaviour the reset was there for: once a retry finally produces
        genuine track, the segment is a first-class citizen again and a later
        degradation gets a fresh budget."""
        engine, _user_id, _project_id = degraded_env(
            _degraded_segment(route_degrade_retries=MAX_DEGRADE_RETRIES - 1))

        assert self._run_sweep_and_resolve(engine, monkeypatch, degraded=False) == 1
        seg = json.loads(_segment_row(engine).segment_json)
        assert seg["route_degrade_retries"] == 0
        assert seg["route_degraded"] is False


# ── Stale resolver stamps (issue #364) ───────────────────────────────────────
#
# The sweep above only ever sees a resolve that failed. #359 was a resolve that
# *succeeded* and was wrong — strategy=relation_endpoints, degraded=False, a
# plausible 492 km line starting 13.9 km from the station — so fixing the
# resolver in #361 reached none of the trips it had already drawn. These cover
# the mechanism that does reach them.


def _stale_segment(**overrides):
    """A rail segment resolved cleanly by a resolver older than the stamp.

    Note what is *absent*: no ``route_resolver_version`` key at all. That is the
    literal shape of every segment row written before #364, and the population
    the sweep exists to reach — a test that seeded ``0`` explicitly would pass
    while ``from_dict`` defaulted the missing key to anything at all.
    """
    seg = {
        "id": "seg-1", "segment_type": "train",
        "route_status": "resolved", "route_mode": "rail",
        "route_polyline": json.dumps([[0.0, 0.0], [1.0, 1.0]]),
        "route_degraded": False, "route_hafas_failed": False,
        "route_edited": False,
        "hafas_provider": "db", "train_number": "ICE 596",
        "date": "2026-08-01",
    }
    seg.update(overrides)
    return seg


@pytest.fixture
def stale_env(monkeypatch):
    """One project holding as many segments as the test passes in."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    monkeypatch.setattr(db_module, "engine", engine)
    SQLModel.metadata.create_all(engine)

    def _seed(*segs: dict):
        with Session(engine) as sess:
            user = UserInfo(display_name="A", email="a@e.com")
            sess.add(user); sess.commit(); sess.refresh(user)
            proj = DBProject(user_info_id=user.id, name="Trip")
            sess.add(proj); sess.commit(); sess.refresh(proj)
            for i, seg in enumerate(segs):
                sess.add(DBProjectItem(
                    project_id=proj.id, position=i, item_type="segment",
                    uid=f"u{i}", segment_id=seg["id"],
                    segment_json=json.dumps(seg),
                ))
            sess.commit()
            return engine, user.id, proj.id

    return _seed


def _capture_enqueue(monkeypatch) -> list:
    import src.jobs.queue as queue_mod
    enqueued: list = []
    monkeypatch.setattr(queue_mod, "enqueue",
                        lambda q, f, *a, **k: enqueued.append(a) or True)
    return enqueued


def _seg_json(engine, seg_id: str) -> dict:
    with Session(engine) as sess:
        row = sess.exec(select(DBProjectItem).where(
            DBProjectItem.segment_id == seg_id)).first()
    return json.loads(row.segment_json)


class TestStaleResolverSweep:
    def test_a_segment_with_no_stamp_is_re_resolved(self, stale_env, monkeypatch):
        """The whole point: an unstamped row is "older than any resolver we
        stamped", not "unknown, leave it alone"."""
        engine, user_id, _project_id = stale_env(_stale_segment())
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 1
        user_arg, name_arg, seg_id_arg, params, _started_at, _job_id = enqueued[0]
        assert (user_arg, name_arg, seg_id_arg) == (user_id, "Trip", "seg-1")
        # The train the user picked is carried into the retry, same as the
        # degraded sweep — a re-resolve must not quietly become a generic one.
        assert params == {
            "hafas_provider": "db", "train_number": "ICE 596", "date": "2026-08-01",
        }
        assert _seg_json(engine, "seg-1")["route_status"] == "pending"

    def test_a_segment_stamped_current_is_left_alone(self, stale_env, monkeypatch):
        stale_env(_stale_segment(route_resolver_version=RESOLVER_VERSION))
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 0
        assert enqueued == []

    def test_a_stamp_above_the_current_version_is_left_alone(
            self, stale_env, monkeypatch):
        """A rolled-back deployment must not re-resolve everything the newer
        build stamped — the comparison is "below", not "different"."""
        stale_env(_stale_segment(route_resolver_version=RESOLVER_VERSION + 1))
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 0
        assert enqueued == []

    def test_a_hand_edited_track_is_never_re_resolved(self, stale_env, monkeypatch):
        """issue #150. This guard is *not* inherited from the degraded sweep:
        the track-edit endpoint clears route_degraded and route_hafas_failed, so
        that sweep skips a hand-drawn track by accident of the flags. A stale
        stamp has no such accident — an edited segment keeps whatever version it
        was last resolved at — so without an explicit check the first
        RESOLVER_VERSION bump silently discards every manual edit."""
        engine, _user_id, _project_id = stale_env(_stale_segment(route_edited=True))
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 0
        assert enqueued == []
        # Untouched, not merely un-queued.
        seg = _seg_json(engine, "seg-1")
        assert seg["route_status"] == "resolved"
        assert seg["route_edited"] is True

    def test_a_degraded_segment_is_left_to_the_other_sweep(
            self, stale_env, monkeypatch):
        """It is stale too, but sweep_degraded_segments already owns it and will
        stamp the current version as a side effect of its own retry. Disjoint
        candidate sets stop one segment consuming both budgets."""
        stale_env(_stale_segment(route_degraded=True))
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 0
        assert enqueued == []

    def test_a_hafas_fallback_segment_is_left_to_the_other_sweep(
            self, stale_env, monkeypatch):
        stale_env(_stale_segment(route_hafas_failed=True))
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 0
        assert enqueued == []

    def test_a_segment_with_no_stored_geometry_is_left_alone(
            self, stale_env, monkeypatch):
        """Moving a segment's endpoints (update_segment) drops route_polyline
        and puts route_mode back to great_circle, but leaves route_status at
        "resolved". Sweeping that would draw rail track across a segment the
        user had just reset to a plain arc — and there is no old geometry to
        redo in the first place."""
        stale_env(_stale_segment(
            route_polyline=None, route_mode="great_circle"))
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 0
        assert enqueued == []

    def test_a_pending_segment_is_not_re_resolved(self, stale_env, monkeypatch):
        stale_env(_stale_segment(route_status="pending"))
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 0
        assert enqueued == []

    def test_a_flight_segment_is_never_queued(self, stale_env, monkeypatch):
        """_compute_segment_geometry raises ValueError for a flight, so queueing
        one would kill a resolve worker rather than resolve anything."""
        stale_env(_stale_segment(segment_type="flight"))
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == 0
        assert enqueued == []

    def test_one_run_queues_at_most_the_cap(self, stale_env, monkeypatch):
        """A RESOLVER_VERSION bump makes every rail segment in the deployment a
        candidate at once. Without a per-run cap that is the whole backlog
        queued against a single Overpass slot in one pass — the traffic shape
        that got this deployment's IPv4 hard-banned in September 2026."""
        over = MAX_STALE_RESOLVES_PER_SWEEP + 2
        engine, _user_id, _project_id = stale_env(
            *[_stale_segment(id=f"seg-{i}") for i in range(over)])
        enqueued = _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == MAX_STALE_RESOLVES_PER_SWEEP
        assert len(enqueued) == MAX_STALE_RESOLVES_PER_SWEEP

        pending = [i for i in range(over)
                   if _seg_json(engine, f"seg-{i}")["route_status"] == "pending"]
        assert len(pending) == MAX_STALE_RESOLVES_PER_SWEEP

    def test_the_rest_of_the_backlog_is_picked_up_on_the_next_run(
            self, stale_env, monkeypatch):
        """Capping must slow the drain, not stop it: the segments left behind
        are still candidates an hour later."""
        over = MAX_STALE_RESOLVES_PER_SWEEP + 2
        engine, _user_id, _project_id = stale_env(
            *[_stale_segment(id=f"seg-{i}") for i in range(over)])
        _capture_enqueue(monkeypatch)

        assert sweep_stale_resolver_segments() == MAX_STALE_RESOLVES_PER_SWEEP
        # Simulate the queued resolves landing: they stamp the current version.
        for i in range(over):
            if _seg_json(engine, f"seg-{i}")["route_status"] == "pending":
                _stamp_resolved(engine, f"seg-{i}")

        assert sweep_stale_resolver_segments() == over - MAX_STALE_RESOLVES_PER_SWEEP

    def test_a_broken_sweep_does_not_raise(self, stale_env, monkeypatch):
        stale_env(_stale_segment())

        def _boom(*_a, **_kw):
            raise RuntimeError("db unavailable")

        monkeypatch.setattr(route_jobs, "get_session", _boom)
        assert sweep_stale_resolver_segments() == 0   # logged, not raised


def _stamp_resolved(engine, seg_id: str) -> None:
    """What a landing resolve writes back, reduced to the parts these tests need."""
    with Session(engine) as sess:
        row = sess.exec(select(DBProjectItem).where(
            DBProjectItem.segment_id == seg_id)).first()
        data = json.loads(row.segment_json)
        data.update({
            "route_status": "resolved",
            "route_resolver_version": RESOLVER_VERSION,
            "route_strategy": "relation_uic",
        })
        row.segment_json = json.dumps(data)
        sess.add(row); sess.commit()


class TestTheStaleSweepTerminates:
    """The sweep and the resolve it queues must agree, or a version bump becomes
    a permanent hourly re-resolve of the same segments.

    #207 is the precedent: the degraded sweep incremented a counter the resolve
    it queued wrote straight back to 0, so MAX_DEGRADE_RETRIES was unreachable
    and every degraded segment was re-resolved forever. These drive the real
    round trip rather than seeding the stamp.
    """

    @staticmethod
    def _run_sweep_and_resolve(monkeypatch, *, degraded=False, strategy="relation_uic"):
        import api.segments as segments_mod
        import src.jobs.queue as queue_mod

        enqueued: list = []
        monkeypatch.setattr(queue_mod, "enqueue",
                            lambda q, f, *a, **k: enqueued.append((f, a)) or True)
        monkeypatch.setattr(segments_mod, "bust_geo_cache", lambda *a, **k: None)
        monkeypatch.setattr(segments_mod, "warm_geo_cache", lambda *a, **k: None)
        monkeypatch.setattr(segments_mod, "warm_meta_cache", lambda *a, **k: None)

        def _geometry(seg, _params):
            seg.route_hafas_failed = False
            return [[0.0, 0.0], [1.0, 1.0]], 2, degraded, strategy

        monkeypatch.setattr(segments_mod, "_compute_segment_geometry", _geometry)

        swept = sweep_stale_resolver_segments()
        for func, args in enqueued:
            func(*args)
        return swept

    def test_the_resolve_stamps_the_version_and_the_strategy(
            self, stale_env, monkeypatch):
        engine, _user_id, _project_id = stale_env(_stale_segment())

        assert self._run_sweep_and_resolve(monkeypatch) == 1
        seg = _seg_json(engine, "seg-1")
        assert seg["route_status"] == "resolved"
        assert seg["route_resolver_version"] == RESOLVER_VERSION
        assert seg["route_strategy"] == "relation_uic"

        # And it is out of the candidate set — the second hour queues nothing.
        assert self._run_sweep_and_resolve(monkeypatch) == 0

    def test_a_degraded_result_still_leaves_the_stale_set(
            self, stale_env, monkeypatch):
        """A re-resolve that runs while every Overpass mirror is down comes back
        degraded. It is stamped anyway: the stamp says which resolver produced
        the geometry, not whether the answer was good — route_degraded already
        says that, and sweep_degraded_segments owns it from here with its own
        budget. Without this, the segment stays stale forever and re-queues
        every hour against hosts that are refusing us."""
        engine, _user_id, _project_id = stale_env(_stale_segment())

        assert self._run_sweep_and_resolve(
            monkeypatch, degraded=True, strategy="straight") == 1
        seg = _seg_json(engine, "seg-1")
        assert seg["route_degraded"] is True
        assert seg["route_resolver_version"] == RESOLVER_VERSION
        assert seg["route_strategy"] == "straight"

        assert self._run_sweep_and_resolve(monkeypatch) == 0
