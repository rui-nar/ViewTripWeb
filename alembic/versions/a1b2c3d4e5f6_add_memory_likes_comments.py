"""add memory_comment and memory_like tables

Revision ID: a1b2c3d4e5f6
Revises: f1a2b3c4d5e6
Create Date: 2026-05-29 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'memory_comment',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('memory_id', sa.Integer(), nullable=False),
        sa.Column('parent_comment_id', sa.Integer(), nullable=True),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('commenter_name', sa.String(), nullable=False, server_default=''),
        sa.Column('text', sa.String(), nullable=False, server_default=''),
        sa.Column('created_at', sa.String(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['memory_id'], ['memory.id']),
        sa.ForeignKeyConstraint(['parent_comment_id'], ['memory_comment.id']),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_memory_comment_memory_id', 'memory_comment', ['memory_id'])

    op.create_table(
        'memory_like',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('memory_id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('liker_name', sa.String(), nullable=False, server_default=''),
        sa.Column('created_at', sa.String(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['memory_id'], ['memory.id']),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_memory_like_memory_id', 'memory_like', ['memory_id'])


def downgrade() -> None:
    op.drop_index('ix_memory_like_memory_id', table_name='memory_like')
    op.drop_table('memory_like')
    op.drop_index('ix_memory_comment_memory_id', table_name='memory_comment')
    op.drop_table('memory_comment')
