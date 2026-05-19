"""add_polarsteps_step_id_to_memory

Revision ID: e5f6a7b8c9d0
Revises: d3e4f5a6b7c8
Create Date: 2026-05-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a7b8c9d0'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('memory', sa.Column('polarsteps_step_id', sa.Integer(), nullable=True))
    op.create_index('ix_memory_polarsteps_step_id', 'memory', ['polarsteps_step_id'])


def downgrade() -> None:
    op.drop_index('ix_memory_polarsteps_step_id', table_name='memory')
    op.drop_column('memory', 'polarsteps_step_id')
