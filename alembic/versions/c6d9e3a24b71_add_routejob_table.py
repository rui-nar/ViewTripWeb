"""add routejob table (issue #173, phase D)

Durable record of an owed route resolution. The queue can lose a job — a broker
restart without appendonly, a worker killed mid-run, an enqueue that fell back
in-process and then died with the API — and until now the only trace that one
was owed was ``route_status="pending"`` on the segment, with the only recovery
implemented in the Flutter client (five minutes stale, and only when someone
reopened the project).

With this table a startup sweep re-queues anything left non-terminal, so
recovery from a server-side crash is the server's job.

Revision ID: c6d9e3a24b71
Revises: b5c8d2f1a930
Create Date: 2026-07-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c6d9e3a24b71'
down_revision: Union[str, Sequence[str], None] = 'b5c8d2f1a930'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'routejob',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('project_name', sa.String(), nullable=False),
        sa.Column('segment_id', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('started_at', sa.String(), nullable=True),
        sa.Column('params_json', sa.String(), nullable=False, server_default='{}'),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('completed_at', sa.Float(), nullable=True),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_routejob_project_id', 'routejob', ['project_id'])
    op.create_index('ix_routejob_user_info_id', 'routejob', ['user_info_id'])
    op.create_index('ix_routejob_segment_id', 'routejob', ['segment_id'])
    # The startup sweep scans by status; everything else is a point lookup.
    op.create_index('ix_routejob_status', 'routejob', ['status'])


def downgrade() -> None:
    op.drop_index('ix_routejob_status', table_name='routejob')
    op.drop_index('ix_routejob_segment_id', table_name='routejob')
    op.drop_index('ix_routejob_user_info_id', table_name='routejob')
    op.drop_index('ix_routejob_project_id', table_name='routejob')
    op.drop_table('routejob')
