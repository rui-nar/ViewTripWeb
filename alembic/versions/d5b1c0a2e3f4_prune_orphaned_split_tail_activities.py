"""prune orphaned split-tail activities (issue #45 follow-up)

A pre-fix bug in "split activity" left orphaned LOCAL activity rows behind:
deleting a split tail via the timeline only unlinked its `projectitem` and never
deleted the `activity` row (see PR #44, which fixed both the allocation and the
delete path going forward). Those orphans are negative-id rows referenced by zero
timeline items. They are now harmless — the fixed allocator derives the next tail
id from MIN(activity.id) across the whole table, so it can no longer collide with
an orphan — but they are dead clutter. This one-off data migration removes them.

Scoped to `id < 0` (local/split tails only): a real Strava activity (id >= 0) is
NEVER touched, even if momentarily unreferenced. Idempotent — a no-op once clean,
and it sweeps any such orphan across every user, not just the one that triggered
the report.

Revision ID: d5b1c0a2e3f4
Revises: f40e0c0de001
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'd5b1c0a2e3f4'
down_revision: Union[str, Sequence[str], None] = 'f40e0c0de001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Delete orphaned local (negative-id) activity rows."""
    op.execute(
        """
        DELETE FROM activity
        WHERE id < 0
          AND id NOT IN (
              SELECT activity_id FROM projectitem
              WHERE activity_id IS NOT NULL
          )
        """
    )


def downgrade() -> None:
    """No-op: deleted orphans carry no recoverable state and were never valid
    data, so there is nothing to restore."""
