"""add client_token to journalentry

Idempotency guard for journal entry creation, mirroring the Polarsteps
duplicate-import defense on memory (migration c9d0e1f2a3b4 /
uq_memory_project_polarsteps_step_id). Journal entries had no uniqueness
constraint at all: a client-perceived timeout followed by a manual user
retry created a genuine duplicate row with no server-side guard. A client
now sends the same ``client_token`` across retries of one logical save
attempt; the partial unique index rejects a second entry sharing a token
within the same project. NULL tokens (older clients, or none supplied) are
exempt via the partial index, same as the Polarsteps precedent.

Revision ID: 0d253594291c
Revises: cca4c615725d
Create Date: 2026-08-26 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0d253594291c'
down_revision: Union[str, Sequence[str], None] = 'cca4c615725d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX = 'uq_journalentry_project_client_token'
_WHERE = 'client_token IS NOT NULL'


def upgrade() -> None:
    op.add_column('journalentry', sa.Column('client_token', sa.String(), nullable=True))
    op.create_index(
        _INDEX,
        'journalentry',
        ['project_id', 'client_token'],
        unique=True,
        sqlite_where=sa.text(_WHERE),
        postgresql_where=sa.text(_WHERE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name='journalentry')
    op.drop_column('journalentry', 'client_token')
