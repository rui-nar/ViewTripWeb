"""add geometry-edit columns to activity (issue #31)

Adds:
  - is_edited: flag marking a locally edited track so Strava sync skips it.
  - original_polyline / original_elevation_profile_json: one-time pre-edit
    snapshot enabling a reversible "Reset to Strava".

Revision ID: e7f8a9b0c1d2
Revises: d1e2f3a4b5c6
Create Date: 2026-07-02 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite.
    op.add_column(
        'activity',
        sa.Column('is_edited', sa.Boolean(), nullable=False, server_default='0'),
    )
    op.add_column(
        'activity',
        sa.Column('original_polyline', sa.String(), nullable=True),
    )
    op.add_column(
        'activity',
        sa.Column('original_elevation_profile_json', sa.String(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table('activity') as batch_op:
        batch_op.drop_column('original_elevation_profile_json')
        batch_op.drop_column('original_polyline')
        batch_op.drop_column('is_edited')
