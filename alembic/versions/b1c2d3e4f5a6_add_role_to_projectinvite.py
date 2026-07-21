"""add role to projectinvite (issue #109)

Companion roles: invite links now carry the role granted on accept
("viewer" | "editor" | "co-owner"). Existing invites default to "editor",
matching their historical (only) behavior.

Revision ID: b1c2d3e4f5a6
Revises: c7d2e9a4f1b3
Create Date: 2026-07-21 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b1c2d3e4f5a6'
down_revision: Union[str, Sequence[str], None] = 'c7d2e9a4f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projectinvite', sa.Column('role', sa.String(), nullable=False, server_default='editor'))


def downgrade() -> None:
    op.drop_column('projectinvite', 'role')
