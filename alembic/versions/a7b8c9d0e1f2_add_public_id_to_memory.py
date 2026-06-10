"""add public_id to memory

Adds a stable, immutable public identifier to each memory, used in durable
share URLs (``/share/<token>?memory=<public_id>``). Decoupled from the
reassignable primary key so that a delete+recreate or a full project
re-import never breaks an existing shared link.

The column is added nullable, every existing row is backfilled with a fresh
UUID, then a unique index is created. It is kept nullable because SQLite's
limited ALTER support makes a NOT NULL retrofit costly; the model-level
``default_factory`` guarantees the value is always populated for new rows.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-10 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('memory', sa.Column('public_id', sa.String(), nullable=True))

    # Backfill existing rows with a distinct UUID each.
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id FROM memory WHERE public_id IS NULL")
    ).fetchall()
    for (memory_id,) in rows:
        conn.execute(
            sa.text("UPDATE memory SET public_id = :pid WHERE id = :id"),
            {"pid": uuid.uuid4().hex, "id": memory_id},
        )

    op.create_index('ix_memory_public_id', 'memory', ['public_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_memory_public_id', table_name='memory')
    op.drop_column('memory', 'public_id')
