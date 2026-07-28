"""add subscription and user usage tables (issue #121)

Tier plans and payments: ``subscription`` caches what the payment provider says
about a user, ``userusage`` is the running storage counter that quota checks
read instead of walking the filesystem on every upload.

Both are empty on upgrade — a user with no row is on the free plan with zero
counted storage, which is the correct starting state. The nightly reconcile job
fills the counters in.

Revision ID: d7c4b9e1f206
Revises: 90b8faeea0f3
Create Date: 2026-07-28 00:00:00.000000

"""
from typing import Sequence, Union

import sqlmodel
from alembic import op
import sqlalchemy as sa


revision: str = 'd7c4b9e1f206'
down_revision: Union[str, Sequence[str], None] = '90b8faeea0f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'subscription',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('plan', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('status', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('provider', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('provider_customer_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('provider_subscription_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('current_period_end', sa.Float(), nullable=False),
        sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
        sa.Column('admin_override_plan', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('last_event_id', sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column('last_event_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_subscription_user_info_id'), 'subscription',
                    ['user_info_id'], unique=True)
    # Webhooks identify the account by provider customer id, not by ours.
    op.create_index(op.f('ix_subscription_provider_customer_id'), 'subscription',
                    ['provider_customer_id'], unique=False)

    op.create_table(
        'userusage',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('storage_bytes', sa.Integer(), nullable=False),
        sa.Column('reconciled_at', sa.Float(), nullable=False),
        sa.Column('updated_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_userusage_user_info_id'), 'userusage',
                    ['user_info_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_userusage_user_info_id'), table_name='userusage')
    op.drop_table('userusage')
    op.drop_index(op.f('ix_subscription_provider_customer_id'), table_name='subscription')
    op.drop_index(op.f('ix_subscription_user_info_id'), table_name='subscription')
    op.drop_table('subscription')
