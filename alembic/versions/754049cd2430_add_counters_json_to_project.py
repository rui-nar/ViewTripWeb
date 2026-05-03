"""add counters_json to project

Revision ID: 754049cd2430
Revises: b7e4f1c3d2a6
Create Date: 2026-05-03 17:56:13.758177

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '754049cd2430'
down_revision: Union[str, Sequence[str], None] = 'b7e4f1c3d2a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('project', sa.Column('counters_json', sa.String(), nullable=True, server_default='[]'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project', 'counters_json')
