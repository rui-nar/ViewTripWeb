"""unique polarsteps_step_id per project

Defense-in-depth against duplicate Polarsteps imports: once a memory carries a
``polarsteps_step_id`` it must be unique within its project. NULL ids (memories
not sourced from Polarsteps, or pre-step-id rows) are exempt via a partial index.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-20 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9d0e1f2a3b4'
down_revision: Union[str, Sequence[str], None] = 'b8c9d0e1f2a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX = 'uq_memory_project_polarsteps_step_id'
_WHERE = 'polarsteps_step_id IS NOT NULL'


def upgrade() -> None:
    op.create_index(
        _INDEX,
        'memory',
        ['project_id', 'polarsteps_step_id'],
        unique=True,
        sqlite_where=sa.text(_WHERE),
        postgresql_where=sa.text(_WHERE),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name='memory')
