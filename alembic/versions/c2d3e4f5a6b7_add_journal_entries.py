"""add_journal_entries

Revision ID: c2d3e4f5a6b7
Revises: f3a1d8e2c749
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c2d3e4f5a6b7'
down_revision: Union[str, Sequence[str], None] = 'f3a1d8e2c749'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'journalentry',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(), nullable=False),
        sa.Column('time', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('photos_json', sa.String(), nullable=False),
        sa.Column('geo_mode', sa.String(), nullable=False),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lon', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_journalentry_date'), 'journalentry', ['date'], unique=False)
    op.create_index(op.f('ix_journalentry_project_id'), 'journalentry', ['project_id'], unique=False)
    op.add_column('projectitem', sa.Column('journal_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('projectitem', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_projectitem_journal_id_journalentry',
            'journalentry', ['journal_id'], ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('projectitem', schema=None) as batch_op:
        batch_op.drop_constraint('fk_projectitem_journal_id_journalentry', type_='foreignkey')
    op.drop_column('projectitem', 'journal_id')
    op.drop_index(op.f('ix_journalentry_project_id'), table_name='journalentry')
    op.drop_index(op.f('ix_journalentry_date'), table_name='journalentry')
    op.drop_table('journalentry')
