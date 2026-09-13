"""Backfill of prepared activity geometry — issue #369 stage B2.

Every path that writes ``summary_polyline`` now derives the prepared blob beside
it, so anything imported or edited after the upgrade is fast on its first open.
Activities that already existed have no row, and get one lazily the first time
someone opens a trip containing them — correct, but it means the first open of
each legacy trip still pays the cost the whole change exists to remove, once.

This sweep closes that gap in the background instead of waiting for a user to
walk into it.

**Why the scheduler and not RQ.** ``enqueue`` runs the job *inline* when no
broker is configured (``src/jobs/queue.py``), which at start-up would block boot;
and the work here is a bounded trickle of local CPU with no external call, no
retry semantics and nothing to fan out. That is what the scheduler is for, and
the degraded-segment sweep beside it is the same shape.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlmodel import Session, select

from models.db import get_session
from models.project_db import DBActivity, DBActivityGeoPrepared
from src.models.prepared_geo import prepare_polyline, store_prepared_if_unchanged
from src.models.simplify import PREPARED_GEO_VERSION
from src.utils.logging import get_logger
from src.utils.metrics import PREPARED_GEOMETRY_BACKLOG, PREPARED_GEOMETRY_OUTCOMES

_log = get_logger(__name__)

# Per run, at ~16 ms of CPU per activity: about 3 s of work every five minutes,
# in one-activity slices that release the GIL between them. Sized to drain the
# production backlog (959 activities) in about half an hour without being
# noticeable against a request.
MAX_PREPARE_PER_SWEEP = 200

# Where the next run resumes. Without it a row that can never be prepared stays
# a candidate forever — it never gets a prepared row — and ``ORDER BY id LIMIT``
# hands it back first on every run. Two hundred of them at the head of the id
# order and the sweep prepares nothing, silently, forever, while the backlog
# behind them waits.
#
# Process-local on purpose. Losing it on restart costs one pass that re-reads
# rows it has already seen, which is cheap; persisting it would be a table for a
# cursor over a backlog that only ever shrinks.
#
# None means "from the start of the id range", and it must not be 0. Activities
# the app creates itself — GPX imports and split tails — take NEGATIVE ids
# (src/project/local_ids.py), so a cursor starting and wrapping at 0 never sees
# any of them. They are exactly the legacy rows this job exists to reach, and
# the first version of this cursor silently excluded every one.
_resume_after_id: int | None = None


def _candidates(sess: Session, limit: int,
                after_id: int | None) -> list[tuple[int, str]]:
    """Activities after *after_id* with a polyline and no current-version row.

    *after_id* of None means no lower bound — see ``_resume_after_id``.

    E2EE envelopes are excluded here rather than skipped after reading. They are
    the common unpreparable case, and filtering in SQL means they never occupy a
    slot in the batch and their ciphertext is never read at all. ``NOT LIKE
    'v1.%'`` cannot exclude a real polyline: the encoding's alphabet is ASCII
    63-126, which contains neither ``1`` nor ``.``, so no encoded track can begin
    with ``v1.``. The case-insensitivity of SQLite's LIKE is harmless for the
    same reason.

    What SQL cannot see — a polyline that does not decode, or decodes to a single
    point — is still read, and the cursor is what stops those starving the rest.
    """
    prepared = select(DBActivityGeoPrepared.activity_id).where(
        DBActivityGeoPrepared.version == PREPARED_GEO_VERSION)
    query = (
        select(DBActivity.id, DBActivity.summary_polyline)
        .where(DBActivity.summary_polyline.is_not(None),
               DBActivity.summary_polyline.not_like("v1.%"),
               DBActivity.id.not_in(prepared))
    )
    if after_id is not None:
        query = query.where(DBActivity.id > after_id)
    return list(sess.exec(query.order_by(DBActivity.id).limit(limit)).all())


def _publish_backlog() -> int | None:
    """Count the unprepared backlog and publish it as a gauge. None if the count fails.

    Called on EVERY run, including one that found no candidates at all. That
    path matters most: a sweep that runs, reports success and makes no progress
    is the failure this job has already shipped twice — once as starvation, once
    as a cursor that skipped every negative id and so found nothing — and it is
    invisible to the scheduler's own metrics, which count it a success. A gauge
    that stops falling is the signal, and unlike a log line it neither spams once
    the backlog is drained nor goes quiet when the sweep breaks.
    """
    try:
        with get_session() as sess:
            remaining = sess.exec(text(
                "SELECT COUNT(*) FROM activity WHERE summary_polyline IS NOT NULL "
                "AND summary_polyline NOT LIKE 'v1.%' "
                "AND id NOT IN (SELECT activity_id FROM activity_geo_prepared "
                "               WHERE version = :version)"
            ).bindparams(version=PREPARED_GEO_VERSION)).scalar_one()
    except Exception:  # noqa: BLE001 — a failed count must not undo stored rows
        # With the traceback: this query failing is abnormal, and a broken one
        # (a renamed column, say) must be visible rather than summarised away.
        _log.exception("prepared-geometry sweep could not count the remaining backlog")
        return None
    PREPARED_GEOMETRY_BACKLOG.set(remaining)
    return remaining


def sweep_unprepared_geometry(limit: int = MAX_PREPARE_PER_SWEEP) -> int:
    """Prepare up to *limit* activities that have no current row. Returns the count.

    E2EE envelopes never reach here — the candidate query excludes them. What
    does reach here and cannot be prepared (a single-fix track, or a polyline
    that does not decode) gets no row, so it is read again each time the cursor
    comes back round to it. That is a few bytes per such row per pass, and far
    cheaper than a marker row whose only job would be to say "skip this".
    """
    global _resume_after_id
    if limit <= 0:
        return 0
    try:
        with get_session() as sess:
            candidates = _candidates(sess, limit, _resume_after_id)
    except Exception:  # noqa: BLE001 — a broken sweep must not take the scheduler down
        _log.exception("prepared-geometry sweep failed to read candidates")
        return 0

    # A short batch means the end of the id range was reached, so the next run
    # starts over from the beginning; a full one resumes after its last row.
    # Advanced whether or not those rows prepared, which is the whole point.
    _resume_after_id = candidates[-1][0] if len(candidates) == limit else None

    if not candidates:
        _publish_backlog()
        return 0

    prepared = 0
    for activity_id, polyline in candidates:
        # Preparing and storing fail for different reasons and deserve different
        # treatment. A polyline that does not decode fails identically on every
        # pass forever — it is unpreparable, not an error, and a traceback each
        # time would be hundreds of identical ERROR lines a day per such row.
        # A write that fails is abnormal and gets the traceback.
        try:
            blob = prepare_polyline(polyline)
        except Exception:  # noqa: BLE001 — undecodable input is an outcome, not a fault
            blob = None
        if blob is None:
            PREPARED_GEOMETRY_OUTCOMES.labels(outcome="unpreparable").inc()
            continue
        try:
            with get_session() as sess:
                # One transaction per activity, not one per sweep: preparing is
                # slow enough that a single long transaction would hold a write
                # lock across the whole batch, and on SQLite that blocks every
                # writer. A partial sweep is fine — the next one continues.
                #
                # Guarded on the polyline, because preparation happened outside
                # any transaction and a writer may have landed meanwhile. See
                # store_prepared_if_unchanged.
                store_prepared_if_unchanged(sess, activity_id, polyline, blob)
                sess.commit()
            prepared += 1
            PREPARED_GEOMETRY_OUTCOMES.labels(outcome="prepared").inc()
        except Exception:  # noqa: BLE001 — one bad row must not cost the batch
            PREPARED_GEOMETRY_OUTCOMES.labels(outcome="error").inc()
            _log.exception("could not store prepared geometry for activity %s", activity_id)

    remaining = _publish_backlog()

    if prepared:
        _log.info("prepared geometry for %d activities, %s left", prepared,
                  "unknown" if remaining is None else remaining)
    else:
        _log.debug("prepared-geometry sweep: %d candidates, none preparable", len(candidates))
    return prepared
