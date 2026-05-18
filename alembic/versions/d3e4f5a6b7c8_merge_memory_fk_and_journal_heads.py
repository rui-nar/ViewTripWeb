"""merge memory_fk and journal_entries heads

Revision ID: d3e4f5a6b7c8
Revises: c1e2f3a4b5d6, c2d3e4f5a6b7
Create Date: 2026-05-18

"""
from typing import Sequence, Union

revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, Sequence[str], None] = ('c1e2f3a4b5d6', 'c2d3e4f5a6b7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
