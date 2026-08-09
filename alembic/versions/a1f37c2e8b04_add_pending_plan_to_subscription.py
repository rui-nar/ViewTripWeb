"""add pending plan to subscription (issue #153)

A downgrade is scheduled for the end of the paid period rather than applied at
once, so between the request and the switch there is a tier the account is
moving to that ``plan`` must not yet name — ``plan`` is the tier in force, and
overwriting it would take the account down the moment they asked.

Both columns default to "nothing pending", which is correct for every existing
row: no subscription had a scheduled change before this shipped.

Revision ID: a1f37c2e8b04
Revises: c6d9e3a24b71
Create Date: 2026-07-31 00:00:00.000000

"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


revision: str = 'a1f37c2e8b04'
down_revision: Union[str, Sequence[str], None] = 'c6d9e3a24b71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'subscription',
        sa.Column('pending_plan', sqlmodel.sql.sqltypes.AutoString(),
                  nullable=False, server_default=''),
    )
    op.add_column(
        'subscription',
        sa.Column('pending_plan_at', sa.Float(), nullable=False,
                  server_default='0'),
    )


def downgrade() -> None:
    op.drop_column('subscription', 'pending_plan_at')
    op.drop_column('subscription', 'pending_plan')
