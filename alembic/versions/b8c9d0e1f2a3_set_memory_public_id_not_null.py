"""set memory.public_id NOT NULL

The a7b8c9d0e1f2 migration added public_id as nullable and backfilled every
existing row, so no nulls exist. This migration enforces the NOT NULL constraint
to match the DBMemory model and satisfy `alembic check`.

SQLite requires a full table recreation (batch mode) to change column nullability.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8c9d0e1f2a3'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('memory') as batch_op:
        batch_op.alter_column('public_id', existing_type=sa.String(), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table('memory') as batch_op:
        batch_op.alter_column('public_id', existing_type=sa.String(), nullable=True)
