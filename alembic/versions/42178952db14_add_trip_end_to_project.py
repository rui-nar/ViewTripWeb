"""add trip_end to project

Revision ID: 42178952db14
Revises: 754049cd2430
Create Date: 2026-05-03 18:11:17.864124

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '42178952db14'
down_revision: Union[str, Sequence[str], None] = '754049cd2430'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('project', sa.Column('trip_end', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project', 'trip_end')
