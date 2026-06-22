"""add elevation_profile_low_res_json to activity (low-res-first chart)

Stores a downsampled (~300 pt) copy of each activity's elevation profile so the
chart renders from the lightweight meta load before the multi-MB full profile
streams in. Backfills existing rows from elevation_profile_json once.

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-06-22 00:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd1e2f3a4b5c6'
down_revision: Union[str, Sequence[str], None] = 'c9d0e1f2a3b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite.
    op.add_column(
        'activity',
        sa.Column('elevation_profile_low_res_json', sa.Text(), nullable=True),
    )
    _backfill()


def _backfill() -> None:
    """Downsample existing full profiles into the new column (one-time)."""
    from src.project.elevation_downsample import downsample_elevation

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, elevation_profile_json FROM activity "
        "WHERE elevation_profile_json IS NOT NULL "
        "AND elevation_profile_low_res_json IS NULL"
    )).fetchall()
    for row_id, ep_json in rows:
        if not ep_json:
            continue
        try:
            ep = json.loads(ep_json)
            d = ep.get("distances_km") or []
            e = ep.get("elevations_m") or []
            if not d or not e:
                continue
            dd, ee = downsample_elevation(d, e)
            low = json.dumps({"distances_km": dd, "elevations_m": ee})
        except Exception:
            continue  # best-effort; population also happens at enrichment time
        bind.execute(
            sa.text(
                "UPDATE activity SET elevation_profile_low_res_json = :v "
                "WHERE id = :id"
            ),
            {"v": low, "id": row_id},
        )


def downgrade() -> None:
    with op.batch_alter_table('activity') as batch_op:
        batch_op.drop_column('elevation_profile_low_res_json')
