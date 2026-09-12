"""add activity_geo_prepared (issue #369)

A side table holding each activity's track prepared for zoom-level-of-detail
serving: the strided working set as 1e5-scaled int32 pairs plus one byte per
vertex naming the lowest zoom level that keeps it. Written whenever a
polyline is written, read by the simplified geo endpoints, so opening a trip
no longer decodes and simplifies every activity on the request path.

A side table, not a column on ``activity``: that table is read by
``sess.get()`` and by ``include_heavy=False`` loads that already defer two
overflow columns; a third big column would have to be deferred everywhere or
it slows ``/meta``.

No backfill here — rows are written lazily on first read and by the sweep of
stage B2, so the upgrade itself is instant on any database.

Revision ID: 04a606ace483
Revises: c4a9e1f70b38
Create Date: 2026-09-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '04a606ace483'
down_revision: Union[str, Sequence[str], None] = 'c4a9e1f70b38'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'activity_geo_prepared',
        sa.Column('activity_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('blob', sa.LargeBinary(), nullable=False),
        sa.ForeignKeyConstraint(['activity_id'], ['activity.id']),
        sa.PrimaryKeyConstraint('activity_id'),
    )


def downgrade() -> None:
    op.drop_table('activity_geo_prepared')
