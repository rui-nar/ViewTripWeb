"""add polarstepstoken and projectsyncmeta tables

Revision ID: 6b70d5b00dde
Revises: 42178952db14
Create Date: 2026-05-08 00:08:05.605525

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6b70d5b00dde'
down_revision: Union[str, Sequence[str], None] = '42178952db14'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'polarstepstoken',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('remember_token', sa.String(), nullable=False),
        sa.Column('polarsteps_user_id', sa.Integer(), nullable=False),
        sa.Column('polarsteps_username', sa.String(), nullable=False),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_polarstepstoken_user_info_id'),
        'polarstepstoken', ['user_info_id'], unique=True,
    )

    op.create_table(
        'projectsyncmeta',
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('linked_ps_trip_id', sa.Integer(), nullable=True),
        sa.Column('auto_sync_enabled', sa.Boolean(), nullable=False),
        sa.Column('last_strava_sync_at', sa.Float(), nullable=True),
        sa.Column('last_ps_sync_at', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.PrimaryKeyConstraint('project_id'),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('projectsyncmeta')
    op.drop_index(op.f('ix_polarstepstoken_user_info_id'), table_name='polarstepstoken')
    op.drop_table('polarstepstoken')
