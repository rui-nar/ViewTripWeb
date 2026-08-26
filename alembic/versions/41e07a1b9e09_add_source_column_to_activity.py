"""add source column to activity

Adds:
  - source: import origin. NULL = from Strava (today's implicit default),
    "gpx" = imported from a GPX file.

Revision ID: 41e07a1b9e09
Revises: cca4c615725d
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '41e07a1b9e09'
down_revision: Union[str, Sequence[str], None] = 'cca4c615725d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite.
    op.add_column(
        'activity',
        sa.Column('source', sa.String(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table('activity') as batch_op:
        batch_op.drop_column('source')
