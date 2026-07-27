"""add pending invites and email verification (issue #110)

Three changes:

- ``projectpendinginvite`` — an invite addressed to one email address, with
  its own token, so it can be revoked individually and matched to an account
  at registration.
- ``emailverification`` — a live verification token, at most one per user.
- ``userinfo.email_verified`` — the soft gate on sending and receiving invites.

The backfill sets ``userinfo.email`` from ``localuser.username`` where it is
empty. Registration used to hardcode ``email=""`` on local accounts while the
username was already an address, so this recovers data that was collected and
then discarded.

Existing Google accounts are marked verified — Google asserted the address
when it issued the id_token, so re-verifying it would be friction with no
security gain. Local accounts are left unverified: nothing in the system ever
checked that those addresses were real, which is exactly the hole this closes.

Revision ID: c8f1a2b3d4e5
Revises: f68e7e215b0f
Create Date: 2026-07-27 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c8f1a2b3d4e5'
down_revision: Union[str, Sequence[str], None] = 'f68e7e215b0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'projectpendinginvite',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('invited_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('accepted_at', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['project.id']),
        sa.ForeignKeyConstraint(['invited_by'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('project_id', 'email'),
    )
    op.create_index(op.f('ix_projectpendinginvite_project_id'),
                    'projectpendinginvite', ['project_id'], unique=False)
    op.create_index(op.f('ix_projectpendinginvite_email'),
                    'projectpendinginvite', ['email'], unique=False)
    op.create_index(op.f('ix_projectpendinginvite_token'),
                    'projectpendinginvite', ['token'], unique=True)

    op.create_table(
        'emailverification',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('token', sa.String(), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.Column('expires_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_emailverification_user_info_id'),
                    'emailverification', ['user_info_id'], unique=True)
    op.create_index(op.f('ix_emailverification_token'),
                    'emailverification', ['token'], unique=True)

    op.add_column('userinfo', sa.Column(
        'email_verified', sa.Boolean(), nullable=False,
        server_default=sa.false()))

    # Recover the address that registration collected as the username and then
    # threw away. Lowercased to match src/email/address.normalize_email — a
    # mixed-case row here would never match an invite.
    op.execute("""
        UPDATE userinfo
           SET email = (SELECT lower(localuser.username)
                          FROM localuser
                         WHERE localuser.id = userinfo.local_auth_id)
         WHERE (email IS NULL OR email = '')
           AND local_auth_id IS NOT NULL
           AND (SELECT localuser.username FROM localuser
                 WHERE localuser.id = userinfo.local_auth_id) LIKE '%@%.%'
    """)

    op.execute("""
        UPDATE userinfo
           SET email_verified = 1
         WHERE auth_provider = 'google' AND email != ''
    """)


def downgrade() -> None:
    op.drop_column('userinfo', 'email_verified')

    op.drop_index(op.f('ix_emailverification_token'), table_name='emailverification')
    op.drop_index(op.f('ix_emailverification_user_info_id'), table_name='emailverification')
    op.drop_table('emailverification')

    op.drop_index(op.f('ix_projectpendinginvite_token'), table_name='projectpendinginvite')
    op.drop_index(op.f('ix_projectpendinginvite_email'), table_name='projectpendinginvite')
    op.drop_index(op.f('ix_projectpendinginvite_project_id'), table_name='projectpendinginvite')
    op.drop_table('projectpendinginvite')
