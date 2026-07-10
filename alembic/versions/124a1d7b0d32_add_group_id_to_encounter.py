"""add group_id to encounter (issue #56)

An encounter can now reference either a person or a group directly (not just a
grouped person, which was already masked on the map). Adds a nullable
`encounter.group_id` FK to `person_group.id`, and relaxes `encounter.person_id`
to nullable — exactly one of the two is set going forward, enforced at the API
layer (see api/encounters.py).

SQLite requires batch mode (table recreation) to change column nullability.

Revision ID: 124a1d7b0d32
Revises: 50c0de5f6a7b
Create Date: 2026-07-10 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '124a1d7b0d32'
down_revision: Union[str, Sequence[str], None] = '50c0de5f6a7b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('encounter', sa.Column('group_id', sa.Integer(), nullable=True))
    op.create_index('ix_encounter_group_id', 'encounter', ['group_id'])
    with op.batch_alter_table('encounter', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_encounter_group_id_person_group',
            'person_group', ['group_id'], ['id'],
        )
        batch_op.alter_column('person_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('encounter', schema=None) as batch_op:
        batch_op.alter_column('person_id', existing_type=sa.Integer(), nullable=False)
        batch_op.drop_constraint('fk_encounter_group_id_person_group', type_='foreignkey')
    op.drop_index('ix_encounter_group_id', table_name='encounter')
    op.drop_column('encounter', 'group_id')
