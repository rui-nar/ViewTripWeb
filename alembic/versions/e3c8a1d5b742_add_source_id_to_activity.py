"""add source_id to activity — fingerprint of an imported track (issue #260)

An activity's ``id`` says which row it is; for a Strava sync that is also which
real-world activity it is, because the id IS Strava's id and an upsert on it is
idempotent by construction. A GPX import has no such handle: it takes a local
id allocated at random, so importing the same file twice produced two
overlapping activities, doubled the trip's distance and climb, and gave the user
nothing to notice it by.

``source_id`` is that missing handle — a fingerprint of the imported track,
hashed from its coordinates and start time (see ``src/project/local_ids.py``).
Indexed because every import looks it up.

Deliberately NOT unique at the database level. The same track legitimately
belongs to more than one trip — a commute ridden on a tour, a loop walked on two
different holidays — so "already imported" is a question about one project's
timeline, not about the whole table, and the import endpoint asks it that way.

No backfill. Existing GPX imports keep a NULL fingerprint: the bytes they came
from are long gone, and inventing one from the stored geometry would be a
different hash than the importer computes from a file (the stored profile has
been through interpolation and repair since). They simply do not participate in
duplicate detection, which is what they did before this column existed.

Revision ID: e3c8a1d5b742
Revises: d2b7e4c81f59
Create Date: 2026-09-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3c8a1d5b742'
down_revision: Union[str, Sequence[str], None] = 'd2b7e4c81f59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite.
    op.add_column('activity', sa.Column('source_id', sa.String(), nullable=True))
    op.create_index('ix_activity_source_id', 'activity', ['source_id'])


def downgrade() -> None:
    op.drop_index('ix_activity_source_id', table_name='activity')
    with op.batch_alter_table('activity') as batch_op:
        batch_op.drop_column('source_id')
