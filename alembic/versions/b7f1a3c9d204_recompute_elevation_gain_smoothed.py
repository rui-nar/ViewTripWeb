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

    updated = 0
    encrypted = 0
    skipped = 0
    for row_id, ep_json in rows:
        if is_encrypted_envelope(ep_json):
            encrypted += 1
            continue
        try:
            elevations = (json.loads(ep_json) or {}).get("elevations_m") or []
        except (ValueError, TypeError, AttributeError):
            skipped += 1
            continue
        if len(elevations) < 2:
            skipped += 1
            continue
        bind.execute(
            sa.text("UPDATE activity SET total_elevation_gain = :g WHERE id = :id"),
            {"g": float(elevation_gain(elevations)), "id": row_id},
        )
        updated += 1

    _log.info(
        "elevation-gain backfill: %d recomputed, %d skipped as encrypted "
        "(see issue #366), %d unusable profiles",
        updated, encrypted, skipped,
    )


def downgrade() -> None:
    """No-op: the pre-migration figures were noise-inflated and are not worth
    restoring — and the raw sums are not recoverable from the corrected values
    anyway. Reverting the code alone puts new edits back on the old algorithm."""
