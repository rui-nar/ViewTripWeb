"""add track_style columns to project

Revision ID: f1a2b3c4d5e6
Revises: e5f6a7b8c9d0
Create Date: 2026-05-24 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('project', sa.Column('track_color', sa.String(), nullable=True, server_default='#F97316'))
    op.add_column('project', sa.Column('track_width', sa.Float(), nullable=True, server_default='2.5'))
    op.add_column('project', sa.Column('alternating_track_colors', sa.Boolean(), nullable=True, server_default='0'))


def downgrade() -> None:
    op.drop_column('project', 'alternating_track_colors')
    op.drop_column('project', 'track_width')
    op.drop_column('project', 'track_color')
