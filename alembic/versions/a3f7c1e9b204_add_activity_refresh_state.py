"""add async re-fetch state columns to activity (issue #148)

A Strava re-fetch makes two API calls and can take minutes (rate-limiter waits,
429 backoff), which blew past the client's 30 s HTTP timeout and reported
"re-fetch failed" for work the server often completed. The re-fetch now runs as
a background job and the client polls /meta for these columns.

Adds:
  - refresh_status: NULL (never re-fetched) | pending | resolved | failed.
  - refresh_started_at: ISO-8601 UTC, used to spot a job orphaned by a restart.
  - refresh_error: short message for the UI when a re-fetch fails.

Mirrors the segment route_status / route_started_at / route_error trio.

Revision ID: a3f7c1e9b204
Revises: d7c4b9e1f206
Create Date: 2026-07-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a3f7c1e9b204'
down_revision: Union[str, Sequence[str], None] = 'd7c4b9e1f206'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite. All nullable with no
    # server_default: NULL is the meaningful "never re-fetched" state, so
    # existing rows need no backfill.
    op.add_column('activity', sa.Column('refresh_status', sa.String(), nullable=True))
    op.add_column('activity', sa.Column('refresh_started_at', sa.String(), nullable=True))
    op.add_column('activity', sa.Column('refresh_error', sa.String(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('activity') as batch_op:
        batch_op.drop_column('refresh_error')
        batch_op.drop_column('refresh_started_at')
        batch_op.drop_column('refresh_status')
