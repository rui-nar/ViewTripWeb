"""merge group_id_to_encounter and e2ee heads

Revision ID: a26e2eea9f01
Revises: 124a1d7b0d32, 1604d06d464d
Create Date: 2026-07-10

"""
from typing import Sequence, Union

revision: str = 'a26e2eea9f01'
down_revision: Union[str, Sequence[str], None] = ('124a1d7b0d32', '1604d06d464d')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
