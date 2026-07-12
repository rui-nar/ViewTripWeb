"""add poster job table (issue #14)

Adds the `posterjob` table backing async server-side A0 poster generation:
one row per POST /api/projects/{name}/poster, tracking status/progress and,
once done, the on-disk paths of the rendered PNG/PDF. The original request
(bounds/orientation/config/memories) is persisted as `request_json` so the
background job runner (and later units that replace its internals) can read
the render parameters back out by job id alone.

Revision ID: 8439d6b26a02
Revises: 024698e63236
Create Date: 2026-07-12 20:55:43.419377

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8439d6b26a02'
down_revision: Union[str, Sequence[str], None] = '024698e63236'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'posterjob',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False,
                  server_default=sa.text("'pending'")),
        sa.Column('stage', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('request_json', sa.String(), nullable=False,
                  server_default=sa.text("'{}'")),
        sa.Column('created_at', sa.Float(), nullable=False,
                  server_default=sa.text('0')),
        sa.Column('completed_at', sa.Float(), nullable=True),
        sa.Column('result_png_path', sa.String(), nullable=True),
        sa.Column('result_pdf_path', sa.String(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_posterjob_project_id', 'posterjob', ['project_id'])
    op.create_index('ix_posterjob_user_info_id', 'posterjob', ['user_info_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_posterjob_user_info_id', table_name='posterjob')
    op.drop_index('ix_posterjob_project_id', table_name='posterjob')
    op.drop_table('posterjob')
