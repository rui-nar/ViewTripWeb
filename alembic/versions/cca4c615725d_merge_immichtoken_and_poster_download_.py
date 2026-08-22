"""merge ImmichToken and poster download token heads

Revision ID: cca4c615725d
Revises: 40f9fd701dfb, 604340be73bb
Create Date: 2026-08-22 20:53:40.566735

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'cca4c615725d'
down_revision: Union[str, Sequence[str], None] = ('40f9fd701dfb', '604340be73bb')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
