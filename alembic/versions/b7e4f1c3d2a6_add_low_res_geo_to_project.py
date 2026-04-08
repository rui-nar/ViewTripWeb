"""add low_res_geo_json to project

Revision ID: b7e4f1c3d2a6
Revises: a3f8c2d1e9b5
Create Date: 2026-04-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e4f1c3d2a6'
down_revision: Union[str, Sequence[str], None] = 'a3f8c2d1e9b5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('project', sa.Column('low_res_geo_json', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('project', 'low_res_geo_json')
