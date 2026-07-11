"""add share memory content table

Revision ID: 024698e63236
Revises: a26e2eea9f01
Create Date: 2026-07-11 18:13:22.977340

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '024698e63236'
down_revision: Union[str, Sequence[str], None] = 'a26e2eea9f01'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'share_memory_content',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('memory_id', sa.Integer(), nullable=False),
        sa.Column('token_type', sa.String(), nullable=False, server_default='full'),
        sa.Column('name_ciphertext', sa.String(), nullable=True),
        sa.Column('description_ciphertext', sa.String(), nullable=True),
        sa.Column('created_at', sa.String(), nullable=False, server_default=''),
        sa.ForeignKeyConstraint(['memory_id'], ['memory.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('memory_id', 'token_type', name='uq_share_memory_content_memory_token'),
    )
    op.create_index('ix_share_memory_content_memory_id', 'share_memory_content', ['memory_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_share_memory_content_memory_id', table_name='share_memory_content')
    op.drop_table('share_memory_content')
