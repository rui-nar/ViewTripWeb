"""drop localauthsession, add memory_id FK on projectitem

Revision ID: c1e2f3a4b5d6
Revises: f3a1d8e2c749
Create Date: 2026-05-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'c1e2f3a4b5d6'
down_revision: Union[str, Sequence[str], None] = 'f3a1d8e2c749'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('localauthsession', schema=None) as batch_op:
        batch_op.drop_index('ix_localauthsession_session_id')
        batch_op.drop_index('ix_localauthsession_user_id')
    op.drop_table('localauthsession')

    with op.batch_alter_table('projectitem', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_projectitem_memory_id_memory',
            'memory', ['memory_id'], ['id'],
        )


def downgrade() -> None:
    with op.batch_alter_table('projectitem', schema=None) as batch_op:
        batch_op.drop_constraint('fk_projectitem_memory_id_memory', type_='foreignkey')

    op.create_table(
        'localauthsession',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.String(length=255), nullable=False),
        sa.Column('expiration', sa.DateTime(timezone=True),
                  server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('localauthsession', schema=None) as batch_op:
        batch_op.create_index('ix_localauthsession_session_id', ['session_id'], unique=True)
        batch_op.create_index('ix_localauthsession_user_id', ['user_id'], unique=False)
