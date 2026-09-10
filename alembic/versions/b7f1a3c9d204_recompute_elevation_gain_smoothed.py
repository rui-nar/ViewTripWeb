"""recompute total_elevation_gain with smoothing + hysteresis (issue #260)

Until now ``recompute_track_metrics`` summed every positive elevation delta, so
sensor noise was counted as climbing: each upward flicker was added and no
downward one subtracted it, leaving an error that accumulates in one direction
and grows with the sample count. On a 6000-sample track with a true 600 m climb
and ±1.2 m of ordinary GPS/barometric noise it reported 4094 m.

Every activity whose gain WE derived carries that inflation — hand-edited pieces,
split pieces, and GPX imports. Strava-synced activities do not: their figure
arrives already processed, which is why the same climb could disagree several
fold between two sources inside one trip's stats. This one-off data migration
recomputes the affected rows with :func:`elevation_gain`.

Deliberately NOT touched:

* Rows whose ``elevation_profile_json`` holds a client-side E2EE envelope. The
  server cannot decrypt them, so it cannot recompute them; they are counted and
  logged, and a client-side pass is tracked separately (issue #366).
* Untouched Strava rows (not edited, not GPX) — their gain is Strava's, not ours.
* ``original_elevation_profile_json`` and the ``original_*`` edit-undo snapshot.
  Those record what the geometry WAS, and are only ever restored through
  ``reset_activity_track``, which recomputes metrics through the fixed code path.
* Profiles carrying the ``0.0`` dropout sentinel — see ``_has_elevation_dropout``.

Two known gaps, both deliberate:

* An activity that was edited and then RESET carries an app-derived gain but
  ends up ``is_edited = 0`` with ``source`` NULL (``reset_activity_track``
  recomputes, then clears the flag), so it is indistinguishable from a plain
  Strava row and this migration skips it. Rare, and preferable to overwriting
  real Strava figures on a guess.
* Rows already poisoned by the dropout sentinel keep their existing figure; the
  sentinel itself is a separate defect (issue #374).

Idempotent: re-running recomputes the same values from the same stored profiles.

Revision ID: b7f1a3c9d204
Revises: 43f9efcb0207
Create Date: 2026-09-10 00:00:00.000000

"""
import json
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7f1a3c9d204'
down_revision: Union[str, Sequence[str], None] = '43f9efcb0207'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_log = logging.getLogger("alembic.runtime.migration")

#: How far a series' median elevation must sit from zero before an exact 0.0
#: sample is read as a missing-elevation sentinel rather than a real reading.
_SEA_LEVEL_MARGIN_M = 50.0


def _has_elevation_dropout(elevations: list) -> bool:
    """True if the series carries the ``0.0`` sentinel rather than real elevation.

    ``points_to_elevation_profile`` stores ``0.0`` for any point that had no
    elevation, so a track through the Alps with three ``<ele>``-less points is
    stored as dipping to sea level and climbing back out — 12 m of real ascent
    reads as 152 m if recomputed from that series verbatim. The live import path
    never saw it, because it drops elevation-less points instead.

    Detected rather than repaired: dropping the zeros here would be inventing
    data, and these rows already hold the figure the live path computed. A row
    whose median elevation is itself near sea level is left to the normal path,
    where a genuine ``0.0`` is simply a valid reading.
    """
    if 0.0 not in elevations:
        return False
    ordered = sorted(elevations)
    median = ordered[len(ordered) // 2]
    return abs(median) > _SEA_LEVEL_MARGIN_M


def upgrade() -> None:
    """Recompute gain for every activity whose gain the app derived itself."""
    # Imported lazily and from the app, not reimplemented here, so the backfill
    # and the live path can never disagree about what "gain" means — same call
    # the enrichment/edit paths make (cf. d1e2f3a4b5c6, which imports
    # downsample_elevation the same way).
    from src.models.track_edit import elevation_gain
    from src.utils.encryption_check import is_encrypted_envelope

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, elevation_profile_json FROM activity "
        "WHERE elevation_profile_json IS NOT NULL "
        "AND (is_edited = 1 OR source = 'gpx')"
    )).fetchall()

    updated_ids = []
    encrypted = 0
    skipped = 0
    dropouts = 0
    for row_id, ep_json in rows:
        if is_encrypted_envelope(ep_json):
            encrypted += 1
            continue
        try:
            profile = json.loads(ep_json) or {}
            elevations = profile.get("elevations_m") or []
            distances = profile.get("distances_km") or []
        except (ValueError, TypeError, AttributeError):
            skipped += 1
            continue
        if len(elevations) < 2:
            skipped += 1
            continue
        if _has_elevation_dropout(elevations):
            dropouts += 1
            continue
        # Distances come from the stored profile so the window spans the same
        # metres of travel the live path measured. Without them a sparse
        # planned-route profile would be scored against a different filter than
        # the one that produced its stored figure.
        if len(distances) != len(elevations):
            distances = None
        bind.execute(
            sa.text("UPDATE activity SET total_elevation_gain = :g WHERE id = :id"),
            {"g": float(elevation_gain(elevations, distances)), "id": row_id},
        )
        updated_ids.append(row_id)

    _invalidate_project_stats(bind, updated_ids)

    _log.info(
        "elevation-gain backfill: %d recomputed, %d skipped as encrypted "
        "(see issue #366), %d with a missing-elevation sentinel (issue #374), "
        "%d unusable profiles",
        len(updated_ids), encrypted, dropouts, skipped,
    )


def _invalidate_project_stats(bind, activity_ids: list) -> None:
    """Clear the cached trip totals of every project holding a corrected row.

    ``project.stats_json`` caches summed elevation across a trip and is only
    recomputed when it is NULL or when a project mutation queues a refresh. This
    migration writes ``activity`` rows directly, so without this a finished trip
    that nobody edits again would show a corrected activity inside an
    uncorrected total — on the owner's stats screen and on any public share page
    — indefinitely. Setting it NULL is enough: both readers recompute on NULL.
    """
    if not activity_ids:
        return
    for start in range(0, len(activity_ids), 500):   # keep the IN list sane
        chunk = activity_ids[start:start + 500]
        placeholders = ", ".join(f":a{i}" for i in range(len(chunk)))
        bind.execute(
            sa.text(
                "UPDATE project SET stats_json = NULL WHERE id IN ("
                f"  SELECT DISTINCT project_id FROM projectitem"
                f"  WHERE activity_id IN ({placeholders})"
                ")"
            ),
            {f"a{i}": aid for i, aid in enumerate(chunk)},
        )


def downgrade() -> None:
    """No-op: the pre-migration figures were noise-inflated and are not worth
    restoring — and the raw sums are not recoverable from the corrected values
    anyway. Reverting the code alone puts new edits back on the old algorithm."""
