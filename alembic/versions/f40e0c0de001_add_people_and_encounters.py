"""add people + encounters (issue #40)

Adds the tables backing "encounters — people met along the trip":
  * person     — owner-only, per-project directory of people met (all fields
                 optional; name may be just a first name or "Unknown")
  * encounter  — links one person to a day/place with an optional note
  * projectitem.encounter_id — FK for encounter timeline items

People/encounters are per-project and owner-only (never shared). New tables +
one nullable column, so existing rows are unaffected.

Revision ID: f40e0c0de001
Revises: e7a1b2c3d4f5
Create Date: 2026-07-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f40e0c0de001'
down_revision: Union[str, Sequence[str], None] = 'e7a1b2c3d4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'person',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('email', sa.String(), nullable=True),
        sa.Column('phone', sa.String(), nullable=True),
        sa.Column('polarsteps', sa.String(), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('avatar_photo', sa.String(), nullable=True),
        sa.Column('created_at', sa.Float(), nullable=False,
                  server_default=sa.text('0')),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_person_project_id', 'person', ['project_id'])

    op.create_table(
        'encounter',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('person_id', sa.Integer(), nullable=False),
        sa.Column('date', sa.String(), nullable=False),
        sa.Column('time', sa.String(), nullable=True),
        sa.Column('description', sa.String(), nullable=True),
        sa.Column('geo_mode', sa.String(), nullable=False,
                  server_default=sa.text("'start_of_day'")),
        sa.Column('lat', sa.Float(), nullable=True),
        sa.Column('lon', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['person_id'], ['person.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_encounter_project_id', 'encounter', ['project_id'])
    op.create_index('ix_encounter_person_id', 'encounter', ['person_id'])
    op.create_index('ix_encounter_date', 'encounter', ['date'])

    op.add_column(
        'projectitem',
        sa.Column('encounter_id', sa.Integer(), nullable=True),
    )
    with op.batch_alter_table('projectitem', schema=None) as batch_op:
        batch_op.create_foreign_key(
            'fk_projectitem_encounter_id_encounter',
            'encounter', ['encounter_id'], ['id'],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projectitem', schema=None) as batch_op:
        batch_op.drop_constraint('fk_projectitem_encounter_id_encounter', type_='foreignkey')
    op.drop_column('projectitem', 'encounter_id')
    op.drop_index('ix_encounter_date', table_name='encounter')
    op.drop_index('ix_encounter_person_id', table_name='encounter')
    op.drop_index('ix_encounter_project_id', table_name='encounter')
    op.drop_table('encounter')
    op.drop_index('ix_person_project_id', table_name='person')
    op.drop_table('person')
