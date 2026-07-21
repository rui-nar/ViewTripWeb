"""add user_info_id to journalentry (issue #106)

Travel-companion feature: journal entries become per-user. A shared project can
hold entries from several users, and each user only ever sees their own. The
column is nullable — NULL means "legacy row owned by the project owner" — and
is backfilled to the project owner so all existing rows carry an explicit
author.

Revision ID: c7d2e9a4f1b3
Revises: a9c4e7f2b8d1
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c7d2e9a4f1b3'
down_revision: Union[str, Sequence[str], None] = 'a9c4e7f2b8d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('journalentry', sa.Column('user_info_id', sa.Integer(), nullable=True))
    op.create_index(op.f('ix_journalentry_user_info_id'), 'journalentry', ['user_info_id'], unique=False)
    with op.batch_alter_table('journalentry', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_journalentry_user_info_id_userinfo',
            'userinfo', ['user_info_id'], ['id'],
        )
    op.execute(
        "UPDATE journalentry SET user_info_id = "
        "(SELECT p.user_info_id FROM project p WHERE p.id = journalentry.project_id)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('journalentry', schema=None) as batch_op:
        batch_op.drop_constraint('fk_journalentry_user_info_id_userinfo', type_='foreignkey')
    op.drop_index(op.f('ix_journalentry_user_info_id'), table_name='journalentry')
    op.drop_column('journalentry', 'user_info_id')
