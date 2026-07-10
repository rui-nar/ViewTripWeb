"""add admin + forced-password-change columns

Adds the columns backing the admin dashboard (issue #25):
  * userinfo.is_admin           — gates access to /api/admin/*
  * userinfo.created_at         — signup timestamp for the per-user breakdown
  * localuser.password_change_required — forces a password change on next login
    (seeded admin, admin-reset accounts)

All three carry server defaults so existing rows are backfilled implicitly on
upgrade. created_at is float (Unix seconds) to match the model and the existing
project.created_at convention.

Revision ID: e7a1b2c3d4f5
Revises: e7f8a9b0c1d2
Create Date: 2026-06-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e7a1b2c3d4f5'
down_revision: Union[str, Sequence[str], None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'userinfo',
        sa.Column('is_admin', sa.Boolean(), nullable=False,
                  server_default=sa.text('0')),
    )
    op.add_column(
        'userinfo',
        sa.Column('created_at', sa.Float(), nullable=False,
                  server_default=sa.text('0')),
    )
    op.add_column(
        'localuser',
        sa.Column('password_change_required', sa.Boolean(), nullable=False,
                  server_default=sa.text('0')),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('localuser', 'password_change_required')
    op.drop_column('userinfo', 'created_at')
    op.drop_column('userinfo', 'is_admin')
