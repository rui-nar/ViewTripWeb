"""add person groups (issue #50)

Adds group support to the people/encounters feature:
  * person_group   — owner-only, per-project named group with nationalities + socials
  * person.group_id — nullable FK; a person belongs to at most one group

New table + one nullable column, so existing rows are unaffected.

Revision ID: 50c0de5f6a7b
Revises: f7e8d9c0b1a2
Create Date: 2026-07-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '50c0de5f6a7b'
down_revision: Union[str, Sequence[str], None] = 'f7e8d9c0b1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'person_group',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('nationalities_json', sa.String(), nullable=True),
        sa.Column('socials_json', sa.String(), nullable=True),
        sa.Column('created_at', sa.Float(), nullable=False,
                  server_default=sa.text('0')),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_person_group_project_id', 'person_group', ['project_id'])

    op.add_column('person', sa.Column('group_id', sa.Integer(), nullable=True))
    op.create_index('ix_person_group_id', 'person', ['group_id'])
    with op.batch_alter_table('person', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_person_group_id_person_group',
            'person_group', ['group_id'], ['id'],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('person', schema=None) as batch_op:
        batch_op.drop_constraint('fk_person_group_id_person_group', type_='foreignkey')
    op.drop_index('ix_person_group_id', table_name='person')
    op.drop_column('person', 'group_id')
    op.drop_index('ix_person_group_project_id', table_name='person_group')
    op.drop_table('person_group')
