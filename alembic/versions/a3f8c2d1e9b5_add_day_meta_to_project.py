"""add day_meta to project

Revision ID: a3f8c2d1e9b5
Revises: ea002876cb8d
Create Date: 2026-04-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f8c2d1e9b5'
down_revision: Union[str, Sequence[str], None] = 'ea002876cb8d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('project', sa.Column('day_meta_json', sa.String(), nullable=True, server_default='{}'))
    op.add_column('project', sa.Column('sleeping_options_json', sa.String(), nullable=True, server_default='[]'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project', 'day_meta_json')
    op.drop_column('project', 'sleeping_options_json')
