"""add trip_start to project

Revision ID: ecb730945e37
Revises: 572a9bb2d2a8
Create Date: 2026-03-31 13:24:20.962332

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ecb730945e37'
down_revision: Union[str, Sequence[str], None] = '572a9bb2d2a8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('project', sa.Column('trip_start', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project', 'trip_start')
