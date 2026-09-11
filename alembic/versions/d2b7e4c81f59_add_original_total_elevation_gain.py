"""add original_total_elevation_gain to activity (issue #386)

Editing a track used to recompute its elevation gain from scratch. For a
Strava-synced activity that threw away Strava's own figure — measured from data
we never receive and corrected in ways we cannot reproduce — and replaced it
with ours, so trimming fifty metres off a ride could move its climb by hundreds
of metres. Splitting was worse: each piece was measured independently, so the
pieces did not sum to the track they came out of.

Edits now scale the existing figure by the share the new geometry accounts for,
the same treatment moving and elapsed time already get. That leaves one thing
to store: what the number was before the first edit, so a reset can put it back.
This column is that snapshot, and it lives and dies with the ``original_polyline``
and ``original_elevation_profile_json`` beside it — written on the first edit,
cleared on reset.

No backfill. NULL means "never edited, nothing to restore", which is exactly
what an unedited row should say, and the edit path falls back to recomputing
when it finds no snapshot — which is what it did for every row before today.

Revision ID: d2b7e4c81f59
Revises: c4a9e1f70b38
Create Date: 2026-09-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd2b7e4c81f59'
down_revision: Union[str, Sequence[str], None] = 'c4a9e1f70b38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite.
    op.add_column(
        'activity',
        sa.Column('original_total_elevation_gain', sa.Float(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table('activity') as batch_op:
        batch_op.drop_column('original_total_elevation_gain')
