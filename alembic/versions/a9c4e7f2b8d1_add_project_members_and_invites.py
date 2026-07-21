"""add project members and invites (issue #106)

Travel-companion feature: ``projectmember`` grants a non-owner user editor
access to a project; ``projectinvite`` holds the invite-link token that
creates memberships on accept.

Revision ID: a9c4e7f2b8d1
Revises: b97eab3d11cf
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a9c4e7f2b8d1'
down_revision: Union[str, Sequence[str], None] = 'b97eab3d11cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'projectmember',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('invited_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.ForeignKeyConstraint(['invited_by'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'user_info_id'),
    )
    op.create_index(op.f('ix_projectmember_project_id'), 'projectmember', ['project_id'], unique=False)
    op.create_index(op.f('ix_projectmember_user_info_id'), 'projectmember', ['user_info_id'], unique=False)

    op.create_table(
        'projectinvite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['created_by'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_projectinvite_project_id'), 'projectinvite', ['project_id'], unique=False)
    op.create_index(op.f('ix_projectinvite_token'), 'projectinvite', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_projectinvite_token'), table_name='projectinvite')
    op.drop_index(op.f('ix_projectinvite_project_id'), table_name='projectinvite')
    op.drop_table('projectinvite')
    op.drop_index(op.f('ix_projectmember_user_info_id'), table_name='projectmember')
    op.drop_index(op.f('ix_projectmember_project_id'), table_name='projectmember')
    op.drop_table('projectmember')
