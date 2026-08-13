"""Durable lifecycle for route-resolution jobs (issue #173, phase D).

A ``DBRouteJob`` row is created when a resolve is requested and advanced to a
terminal status when it finishes. The row — not the queue entry, and not the
segment's ``route_status`` — is the record that work is owed.

That matters because every layer above it can lose the job: RQ without
``appendonly`` loses the queue on a broker restart, a worker killed mid-run
loses whatever it held, and an enqueue that fell back to ``BackgroundTasks``
dies with the API process. Before this, the only component that ever noticed was
the Flutter client's stale-pending recovery — five minutes late, and only if
someone reopened the project.

:func:`sweep_orphaned_jobs` runs at API startup and re-queues anything left
non-terminal.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlmodel import select

from models.db import get_session
from models.project_db import DBProject, DBProjectItem, DBRouteJob
from src.models.project import ConnectingSegment
from src.project.project_repo import ProjectRepo
from src.utils.logging import get_logger

_log = get_logger(__name__)
_repo = ProjectRepo()

# A job that dies mid-run is re-queued by the next sweep. One that dies *because
# of its own inputs* would be re-queued forever, taking a worker with it every
# boot — so the sweep gives up and fails it loudly instead.
MAX_ATTEMPTS = 3

# A degraded resolve (route_degraded=True) is a straight endpoint chord used
# because Overpass failed every mirror/strategy at request time — not a
# permanent verdict; the same mirror flakiness is often transient (issue
# #207). sweep_degraded_segments retries a degraded segment up to this many
# times before leaving it alone — still manually retryable from the tile,
# same as any other resolve.
MAX_DEGRADE_RETRIES = 5

TERMINAL = ("done", "failed")


def create_job(
    user_info_id: int,
    project_id: int,
    project_name: str,
    segment_id: str,
    started_at: str,
    params: Dict[str, Any],
) -> int:
    """Record that a resolve is owed. Returns the job id."""
    with get_session() as sess:
        # Supersede any earlier attempt for this segment: the newer trigger owns
        # the outcome, and leaving the old row pending would have the sweep
        # re-queue a job whose verdict the token guard now discards anyway.
        for stale in sess.exec(
            select(DBRouteJob).where(
                DBRouteJob.project_id == project_id,
                DBRouteJob.segment_id == segment_id,
                DBRouteJob.status.notin_(TERMINAL),
            )
        ).all():
            stale.status = "failed"
            stale.error_message = "superseded by a newer resolve request"
            stale.completed_at = time.time()
            sess.add(stale)

        job = DBRouteJob(
            project_id=project_id,
            user_info_id=user_info_id,
            project_name=project_name,
            segment_id=segment_id,
            started_at=started_at,
            params_json=json.dumps(params or {}),
        )
        sess.add(job)
        sess.commit()
        sess.refresh(job)
        return job.id


def mark_running(job_id: Optional[int]) -> None:
    _set_status(job_id, "running")


def mark_done(job_id: Optional[int]) -> None:
    _set_status(job_id, "done", completed=True)


def mark_failed(job_id: Optional[int], error: str) -> None:
    _set_status(job_id, "failed", completed=True, error=error)


def _set_status(
    job_id: Optional[int], status: str, *, completed: bool = False,
    error: Optional[str] = None,
) -> None:
    """Advance a job row. Never raises — bookkeeping must not sink the job."""
    if job_id is None:
        return
    try:
        with get_session() as sess:
            job = sess.get(DBRouteJob, job_id)
            if job is None:
                return
            job.status = status
            if error is not None:
                job.error_message = error[:500]
            if completed:
                job.completed_at = time.time()
            sess.add(job)
            sess.commit()
    except Exception:  # noqa: BLE001
        _log.exception("could not set route job %s to %s", job_id, status)


def sweep_orphaned_jobs() -> int:
    """Re-queue every non-terminal route job. Returns how many were re-queued.

    Called once at API startup. Anything still ``pending``/``running`` when the
    process starts is by definition orphaned — nothing was executing it a moment
    ago, because nothing was running at all.

    Deliberately not scoped by age: at startup there is no in-flight work to
    accidentally duplicate, which is exactly what makes startup the right moment
    to do this. (The client's five-minute staleness window existed only because
    it *could not* know whether a job was still running.)
    """
    from api.segments import _resolve_route_job
    from src.jobs.queue import QUEUE_RESOLVE, enqueue

    requeued = 0
    try:
        with get_session() as sess:
            orphans = sess.exec(
                select(DBRouteJob).where(DBRouteJob.status.notin_(TERMINAL))
            ).all()
            pending = [
                (j.id, j.user_info_id, j.project_name, j.segment_id,
                 json.loads(j.params_json or "{}"), j.started_at, j.attempts)
                for j in orphans
            ]
            for job in orphans:
                if job.attempts + 1 >= MAX_ATTEMPTS:
                    job.status = "failed"
                    job.error_message = (
                        f"abandoned after {MAX_ATTEMPTS} attempts — the job did not "
                        "survive repeated restarts")
                    job.completed_at = time.time()
                else:
                    job.attempts += 1
                sess.add(job)
            sess.commit()
    except Exception:  # noqa: BLE001 — a broken sweep must not stop the app booting
        _log.exception("route job sweep failed to read orphans")
        return 0

    for job_id, user_id, name, seg_id, params, started_at, attempts in pending:
        if attempts + 1 >= MAX_ATTEMPTS:
            _log.warning("route job %s abandoned after %d attempts", job_id, attempts)
            _fail_segment_for(user_id, name, seg_id, started_at)
            continue
        try:
            enqueue(QUEUE_RESOLVE, _resolve_route_job,
                    user_id, name, seg_id, params, started_at, job_id)
            requeued += 1
        except Exception:  # noqa: BLE001
            _log.exception("could not re-queue route job %s", job_id)

    if requeued:
        _log.info("re-queued %d orphaned route job(s) at startup", requeued)
    return requeued


def _fail_segment_for(
    user_info_id: int, name: str, seg_id: str, started_at: Optional[str]
) -> None:
    """Flip an abandoned job's segment out of "pending" so the UI stops spinning."""
    from api.segments import _mark_segment_failed

    _mark_segment_failed(
        user_info_id, name, seg_id,
        "Route resolution did not survive a server restart — please try again.",
        started_at,
    )


def sweep_degraded_segments() -> int:
    """Re-attempt every degraded, not-yet-exhausted segment. Returns how many.

    Called on a schedule (hourly, api/router.py) — unlike :func:`sweep_orphaned_jobs`
    there is no startup/crash urgency here, just giving a flaky Overpass mirror
    room to recover between attempts (issue #207).

    Reads candidates directly off ``DBProjectItem`` rows rather than loading
    whole projects via :class:`ProjectRepo` — the same reason
    :func:`sweep_orphaned_jobs` reads ``DBRouteJob`` rows directly instead of
    going through a heavier path.
    """
    from api.geo import bust_geo_cache
    from api.segments import _resolve_route_job
    from src.jobs.queue import QUEUE_RESOLVE, enqueue

    candidates: list = []
    try:
        with get_session() as sess:
            rows = sess.exec(
                select(DBProjectItem, DBProject.user_info_id, DBProject.name)
                .join(DBProject, DBProject.id == DBProjectItem.project_id)
                .where(DBProjectItem.item_type == "segment")
            ).all()
            for row, user_info_id, name in rows:
                seg = ConnectingSegment.from_dict(json.loads(row.segment_json or "{}"))
                if seg.route_status != "resolved" or not seg.route_degraded:
                    continue
                if seg.route_degrade_retries >= MAX_DEGRADE_RETRIES:
                    continue
                candidates.append((
                    row.project_id, user_info_id, name, seg.id,
                    seg.route_degrade_retries,
                    {
                        "hafas_provider": seg.hafas_provider,
                        "train_number": seg.train_number,
                        "date": seg.date,
                    },
                ))
    except Exception:  # noqa: BLE001 — a broken sweep must not take the scheduler down
        _log.exception("degraded-segment sweep failed to read candidates")
        return 0

    retried = 0
    for project_id, user_info_id, name, seg_id, retries, params in candidates:
        started_at = datetime.now(timezone.utc).isoformat()
        try:
            with get_session() as sess:
                # Only if still resolved+degraded: a manual trigger or edit
                # racing this sweep owns the outcome instead.
                written = _repo.update_segment_fields(
                    sess, project_id, seg_id,
                    {
                        "route_status": "pending",
                        "route_started_at": started_at,
                        "route_degrade_retries": retries + 1,
                    },
                    expect_status="resolved",
                )
                sess.commit()
        except Exception:  # noqa: BLE001
            _log.exception("could not mark seg=%s pending for a degraded retry", seg_id)
            continue
        if not written:
            continue
        # Mirrors resolve_segment_route: a cached /meta must not keep serving
        # the pre-retry "resolved+degraded" state, including to a client's own
        # periodic degraded-route-upgrade check (project_notifier.dart).
        bust_geo_cache(user_info_id, name)

        job_id = create_job(user_info_id, project_id, name, seg_id, started_at, params)
        try:
            enqueue(QUEUE_RESOLVE, _resolve_route_job,
                    user_info_id, name, seg_id, params, started_at, job_id)
            retried += 1
        except Exception:  # noqa: BLE001
            _log.exception("could not enqueue degraded retry for seg=%s", seg_id)

    if retried:
        _log.info("retried %d degraded segment(s)", retried)
    return retried
