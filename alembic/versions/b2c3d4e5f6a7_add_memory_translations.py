"""add memory_translation table and project languages_json column

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'memory_translation',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('memory_id', sa.Integer(), nullable=False),
        sa.Column('lang_code', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['memory_id'], ['memory.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('memory_id', 'lang_code', name='uq_memory_translation_memory_lang'),
    )
    op.create_index('ix_memory_translation_memory_id', 'memory_translation', ['memory_id'])

    op.add_column('project', sa.Column('languages_json', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('project', 'languages_json')
    op.drop_index('ix_memory_translation_memory_id', table_name='memory_translation')
    op.drop_table('memory_translation')
