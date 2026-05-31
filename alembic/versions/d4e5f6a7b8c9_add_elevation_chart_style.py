"""add elevation_chart_color and elevation_chart_show_line to project

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-05-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = 'd4e5f6a7b8c9'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'project',
        sa.Column('elevation_chart_color', sa.String(), nullable=True),
    )
    op.add_column(
        'project',
        sa.Column('elevation_chart_show_line', sa.Boolean(), nullable=False,
                  server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column('project', 'elevation_chart_show_line')
    op.drop_column('project', 'elevation_chart_color')
