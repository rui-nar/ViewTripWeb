"""add share_token_no_memories and sharevisit table

Revision ID: f3a1d8e2c749
Revises: 6b70d5b00dde
Create Date: 2026-05-13

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op

revision: str = 'f3a1d8e2c749'
down_revision: Union[str, Sequence[str], None] = '6b70d5b00dde'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('project', sa.Column(
        'share_token_no_memories', sqlmodel.sql.sqltypes.AutoString(), nullable=True))
    op.create_index(
        op.f('ix_project_share_token_no_memories'),
        'project', ['share_token_no_memories'], unique=False)

    op.create_table(
        'sharevisit',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('token_type', sa.String(), nullable=False),
        sa.Column('visitor_type', sa.String(), nullable=False),
        sa.Column('anonymous_id', sa.String(), nullable=True),
        sa.Column('user_info_id', sa.Integer(), nullable=True),
        sa.Column('first_seen_at', sa.Float(), nullable=False),
        sa.Column('last_seen_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_sharevisit_project_id'), 'sharevisit', ['project_id'])
    op.create_index(op.f('ix_sharevisit_anonymous_id'), 'sharevisit', ['anonymous_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_sharevisit_anonymous_id'), table_name='sharevisit')
    op.drop_index(op.f('ix_sharevisit_project_id'), table_name='sharevisit')
    op.drop_table('sharevisit')
    op.drop_index(op.f('ix_project_share_token_no_memories'), table_name='project')
    op.drop_column('project', 'share_token_no_memories')
