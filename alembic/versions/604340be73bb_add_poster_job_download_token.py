"""add download_token to poster job (issue #14)

Adds a nullable, indexed `download_token` column to `posterjob`: an
unguessable UUID set on job creation (api/poster.py's create_poster_job) that
backs the unauthenticated "download your poster" link sent in the
done/failed notification email (src/poster/poster_job_runner.py). The
poster's status/download routes are otherwise owner-only behind a JWT, but
that email may be opened on a device with no active session — same pattern
as `DBProject.share_token`.

Revision ID: 604340be73bb
Revises: a1f37c2e8b04
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '604340be73bb'
down_revision: Union[str, Sequence[str], None] = 'a1f37c2e8b04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('posterjob', sa.Column('download_token', sa.String(), nullable=True))
    op.create_index('ix_posterjob_download_token', 'posterjob', ['download_token'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_posterjob_download_token', table_name='posterjob')
    op.drop_column('posterjob', 'download_token')
