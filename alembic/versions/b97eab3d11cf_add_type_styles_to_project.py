"""add per-activity/segment-type style overrides to project (issue #95)

Adds `color_by_type` (opt-in toggle, default off — existing projects keep
today's flat trackColor line rendering unchanged) and `type_styles_json`
(per-type colour/line-style overrides, keyed by activity bucket
ride/run/hike/other or segment type flight/train/bus/boat).

Revision ID: b97eab3d11cf
Revises: 8439d6b26a02
Create Date: 2026-07-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b97eab3d11cf'
down_revision: Union[str, Sequence[str], None] = '8439d6b26a02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('project', sa.Column('color_by_type', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('project', sa.Column('type_styles_json', sa.String(), nullable=False, server_default='{}'))


def downgrade() -> None:
    op.drop_column('project', 'type_styles_json')
    op.drop_column('project', 'color_by_type')
