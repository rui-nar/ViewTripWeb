"""add split_parent_id to activity (issue #143)

split_root_id points every piece of a split family at the family's FIRST piece,
however deep the chain — it cannot say which piece a given one was cut OUT of.
So resetting a piece that had itself been split again restored the span it
covered before that second cut, growing back over its own children with nothing
able to find them (issue #143).

split_parent_id records the immediate parent, so reset can delete the transitive
descendants of whatever is being reset. The root case ("undo the whole split",
issue #141) falls out of that as "the descendants of the root".

Backfill: existing rows get split_parent_id = split_root_id. That reproduces
exactly the pre-#143 behaviour for legacy families — the root reaches every
piece, a piece reaches none — without ever over-deleting. Inferring the real
parent from chronological order would NOT be safe: re-splitting the head inserts
a new piece between the head and its existing tail, so a piece's chronological
predecessor is not necessarily its parent, and a wrong guess deletes the wrong
activities. Legacy deep chains therefore keep the #143 behaviour until they are
split again; new splits are accurate from the start.

Revision ID: 90b8faeea0f3
Revises: c8f1a2b3d4e5
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '90b8faeea0f3'
down_revision: Union[str, Sequence[str], None] = 'c8f1a2b3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite.
    op.add_column(
        'activity',
        sa.Column('split_parent_id', sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f('ix_activity_split_parent_id'), 'activity', ['split_parent_id'],
    )
    op.execute(
        'UPDATE activity SET split_parent_id = split_root_id '
        'WHERE split_root_id IS NOT NULL'
    )


def downgrade() -> None:
    with op.batch_alter_table('activity') as batch_op:
        batch_op.drop_index(op.f('ix_activity_split_parent_id'))
        batch_op.drop_column('split_parent_id')
