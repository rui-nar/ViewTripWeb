"""add split-family columns to activity (issue #45 follow-up)

Adds:
  - split_root_id: id of the original first piece of a split family (NULL on
    a never-split row, or on the root itself). Lets every descendant of a
    split chain be found in one query regardless of how deep the chain goes.
  - split_base_name: the clean pre-split name, captured once on the root so
    renumbering ("<name> (i/N)") never accumulates on top of itself.

Revision ID: f68e7e215b0f
Revises: b1c2d3e4f5a6
Create Date: 2026-07-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f68e7e215b0f'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite.
    op.add_column(
        'activity',
        sa.Column('split_root_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f('ix_activity_split_root_id'), 'activity', ['split_root_id'],
    )
    op.add_column(
        'activity',
        sa.Column('split_base_name', sa.String(), nullable=True),
    )


def downgrade() -> None:
    with op.batch_alter_table('activity') as batch_op:
        batch_op.drop_index(op.f('ix_activity_split_root_id'))
        batch_op.drop_column('split_base_name')
        batch_op.drop_column('split_root_id')
