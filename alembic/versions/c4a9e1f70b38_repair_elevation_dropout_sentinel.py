"""repair elevation profiles storing 0.0 for missing <ele> (issue #374)

``points_to_elevation_profile`` used to store ``0.0`` for any point that carried
no elevation, so a track through the Alps with three ``<ele>``-less points was
stored as diving to sea level and climbing back out. Two things read that as
real: the elevation chart, which plots the stored array verbatim and drew the
dive, and anything recomputing gain from storage — a 300-point track at ~500 m
with three missing points measures 14.4 m of ascent on the live import path
(which drops elevation-less points while keeping their distance) and 232.6 m
recomputed from its own stored profile.

These are exactly the rows ``b7f1a3c9d204`` detected and deliberately skipped
rather than corrupt: it had no way to tell what the missing samples should have
been, so it left the stored figure — the honest one, computed by the live path —
in place. This migration fills the holes the way the fixed writer now does
(linear interpolation by cumulative distance, matching what ``align_points``
already derives when it reads a profile back), and only then recomputes the
gain. So those activities finally get a corrected figure too.

That repair changes the STORED profile, not just a scalar, so it also rebuilds
``elevation_profile_low_res_json`` for every row it rewrites — the chart loads
the low-res copy first, and leaving it behind would keep drawing the dive.

Deliberately NOT touched, following ``b7f1a3c9d204``:

* Rows whose profile is a client-side E2EE envelope — the server holds no key
  and cannot read, let alone repair, them (counted and logged; issue #366).
* Rows whose median elevation is itself near sea level: there a ``0.0`` is a
  valid reading, and "repairing" it would mangle a genuine coastal track.
* ``original_elevation_profile_json`` and the rest of the edit-undo snapshot.
  Those record what the geometry WAS; ``reset_activity_track`` recomputes
  through the fixed code path when it restores them.

Idempotent: the repaired series carries no ``0.0`` any more, so a second run
finds no dropout and does nothing.

Revision ID: c4a9e1f70b38
Revises: b7f1a3c9d204
Create Date: 2026-09-11 00:00:00.000000

"""
import json
import logging
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c4a9e1f70b38'
down_revision: Union[str, Sequence[str], None] = 'b7f1a3c9d204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_log = logging.getLogger("alembic.runtime.migration")

#: How far a series' median elevation must sit from zero before an exact 0.0
#: sample is read as a missing-elevation sentinel rather than a real reading.
#: Same value and same test as ``b7f1a3c9d204._has_elevation_dropout``, which is
#: what decided these rows were unsafe to recompute in the first place — the two
#: must agree, or this pass would repair a row that one never skipped.
_SEA_LEVEL_MARGIN_M = 50.0


def _has_elevation_dropout(elevations: list) -> bool:
    """True if the series carries the ``0.0`` sentinel rather than real elevation."""
    if 0.0 not in elevations:
        return False
    ordered = sorted(elevations)
    median = ordered[len(ordered) // 2]
    return abs(median) > _SEA_LEVEL_MARGIN_M


def upgrade() -> None:
    """Repair sentinel-bearing profiles and recompute their gain."""
    # Imported lazily and from the app, not reimplemented here, so the repair
    # and the live writer can never disagree about what an interpolated gap or
    # a "gain" is — the same calls the import/edit paths make (cf. b7f1a3c9d204
    # and d1e2f3a4b5c6, which import from the app the same way).
    from src.models.track_edit import elevation_gain, interpolate_elevation_gaps
    from src.project.elevation_downsample import downsample_elevation
    from src.utils.encryption_check import is_encrypted_envelope

    bind = op.get_bind()
    # Same predicate as b7f1a3c9d204: the sentinel is only ever written by
    # points_to_elevation_profile, which runs on hand-edited pieces, split
    # pieces and GPX imports. A synced Strava profile's 0.0 is Strava's own
    # reading and none of our business.
    rows = bind.execute(sa.text(
        "SELECT id, elevation_profile_json FROM activity "
        "WHERE elevation_profile_json IS NOT NULL "
        "AND (is_edited = 1 OR source = 'gpx')"
    )).fetchall()

    repaired_ids = []
    encrypted = 0
    skipped = 0
    clean = 0
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
        if len(elevations) < 2 or len(distances) != len(elevations):
            skipped += 1
            continue
        if not _has_elevation_dropout(elevations):
            clean += 1
            continue

        # Map the sentinel back to the "no reading" it always meant, then fill
        # the holes exactly as the fixed writer now does.
        holed = [None if e == 0.0 else float(e) for e in elevations]
        repaired = interpolate_elevation_gaps(distances, holed)
        repaired_json = json.dumps(
            {"distances_km": distances, "elevations_m": repaired})
        low_d, low_e = downsample_elevation(distances, repaired)
        # Distances go in alongside: the smoothing window spans metres of
        # travel, so scoring the series without them filters it differently.
        gain = float(elevation_gain(repaired, distances))
        bind.execute(
            sa.text(
                "UPDATE activity SET elevation_profile_json = :ep, "
                "elevation_profile_low_res_json = :low, "
                "total_elevation_gain = :g WHERE id = :id"
            ),
            {
                "ep": repaired_json,
                "low": json.dumps({"distances_km": low_d, "elevations_m": low_e}),
                "g": gain,
                "id": row_id,
            },
        )
        repaired_ids.append(row_id)

    _invalidate_project_stats(bind, repaired_ids)

    _log.info(
        "elevation-dropout repair: %d profiles repaired and re-gained, "
        "%d already clean, %d skipped as encrypted (see issue #366), "
        "%d unusable profiles",
        len(repaired_ids), clean, encrypted, skipped,
    )


def _invalidate_project_stats(bind, activity_ids: list) -> None:
    """Clear the cached trip totals of every project holding a repaired row.

    ``project.stats_json`` caches summed elevation across a trip and is only
    recomputed when it is NULL or when a project mutation queues a refresh. This
    migration writes ``activity`` rows directly, so without this a finished trip
    that nobody edits again would show a repaired activity inside an unrepaired
    total — on the owner's stats screen and on any public share page —
    indefinitely. Setting it NULL is enough: both readers recompute on NULL.
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
    """No-op: the sentinel values are not recoverable from the interpolated
    series, and restoring a fabricated dive to sea level would be a regression
    rather than a revert. Reverting the code alone puts new imports back on the
    sentinel."""
