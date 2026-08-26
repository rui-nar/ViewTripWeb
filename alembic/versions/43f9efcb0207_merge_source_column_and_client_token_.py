"""merge source_column and client_token heads

Revision ID: 43f9efcb0207
Revises: 41e07a1b9e09, 0d253594291c
Create Date: 2026-08-26

"""
from typing import Sequence, Union


revision: str = '43f9efcb0207'
down_revision: Union[str, Sequence[str], None] = ('41e07a1b9e09', '0d253594291c')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
