"""add uid + segment_id to projectitem (issue #173, phase A)

Item rows had no stable identity: ``save_project`` deleted every row for a
project and bulk-reinserted the list, so primary keys churned on every write.
That forced each mutation, however small, to serialise at project granularity
behind the ``lock_version`` CAS.

Adds:
  - uid: durable per-item identity, unique within a project. Lets the item
    persistence diff insert/update/delete instead of destroying and rebuilding.
  - segment_id: the segment's logical id, which previously existed only inside
    the ``segment_json`` blob. As a column it can be indexed, so the route
    resolver can update one segment's geometry with a targeted UPDATE rather
    than a whole-project save.

Both are backfilled for existing rows: uid with fresh uuid4 hex, segment_id by
reading the id out of each segment row's JSON. uid stays nullable in the schema
(SQLite cannot add a NOT NULL column without a default) but is always populated
on write; the unique index is partial so pre-existing NULLs, if any survive,
cannot collide.

Revision ID: b5c8d2f1a930
Revises: a3f7c1e9b204
Create Date: 2026-07-30 00:00:00.000000

"""
import json
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5c8d2f1a930'
down_revision: Union[str, Sequence[str], None] = 'a3f7c1e9b204'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Native ADD COLUMN — fast on SQLite, no table rewrite.
    op.add_column('projectitem', sa.Column('uid', sa.String(), nullable=True))
    op.add_column('projectitem', sa.Column('segment_id', sa.String(), nullable=True))

    conn = op.get_bind()

    # Backfill uid one row at a time: uuid4 per row, so this cannot be a single
    # set-based UPDATE. Project item counts are in the hundreds, not millions.
    rows = conn.execute(sa.text("SELECT id FROM projectitem WHERE uid IS NULL")).fetchall()
    for (row_id,) in rows:
        conn.execute(
            sa.text("UPDATE projectitem SET uid = :uid WHERE id = :id"),
            {"uid": uuid.uuid4().hex, "id": row_id},
        )

    # Backfill segment_id from the JSON payload. Done in Python rather than with
    # SQLite's json_extract so a malformed blob degrades to NULL instead of
    # failing the whole migration — a segment with no id keeps working through
    # the whole-list path.
    seg_rows = conn.execute(sa.text(
        "SELECT id, segment_json FROM projectitem "
        "WHERE item_type = 'segment' AND segment_json IS NOT NULL"
    )).fetchall()
    for row_id, seg_json in seg_rows:
        try:
            seg_id = (json.loads(seg_json) or {}).get("id") or None
        except (ValueError, TypeError):
            seg_id = None
        if seg_id:
            conn.execute(
                sa.text("UPDATE projectitem SET segment_id = :sid WHERE id = :id"),
                {"sid": str(seg_id), "id": row_id},
            )

    op.create_index(
        'ix_projectitem_project_uid', 'projectitem', ['project_id', 'uid'],
        unique=True, sqlite_where=sa.text('uid IS NOT NULL'),
    )
    op.create_index(
        'ix_projectitem_project_segment', 'projectitem', ['project_id', 'segment_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_projectitem_project_segment', table_name='projectitem')
    op.drop_index('ix_projectitem_project_uid', table_name='projectitem')
    with op.batch_alter_table('projectitem') as batch_op:
        batch_op.drop_column('segment_id')
        batch_op.drop_column('uid')
