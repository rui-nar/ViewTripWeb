"""add E2EE columns and key-material tables (issue #26)

Adds the opaque-storage surface for zero-knowledge encryption. The server holds
no keys and does no crypto — it only stores ciphertext blobs and wrapped keys.

  * enc_version markers on memory / journalentry / project (0 = plaintext,
    >=1 = the in-scope text columns hold self-describing ciphertext blobs).
  * encryption_enabled flag on userinfo (signals clients to expect ciphertext).
  * device_key table (per-device X25519 pubkey + CMK wrapped to it; approval).
  * recovery_wrap table (CMK wrapped under a recovery key or Q&A→Argon2id).

Revision ID: e7f8a9b0c1d2
Revises: d1e2f3a4b5c6
Create Date: 2026-06-30 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
import sqlmodel
from alembic import op


revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-row plaintext/ciphertext markers. server_default backfills existing rows.
    op.add_column('memory', sa.Column(
        'enc_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('journalentry', sa.Column(
        'enc_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('project', sa.Column(
        'enc_version', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('userinfo', sa.Column(
        'encryption_enabled', sa.Boolean(), nullable=False,
        server_default=sa.text('0')))

    op.create_table(
        'device_key',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('public_key', sa.String(), nullable=False),
        sa.Column('label', sa.String(), nullable=False),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.Column('wrapped_cmk', sa.String(), nullable=True),
        sa.Column('ephemeral_public_key', sa.String(), nullable=True),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_device_key_user_info_id'), 'device_key', ['user_info_id'])

    op.create_table(
        'recovery_wrap',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_info_id', sa.Integer(), nullable=False),
        sa.Column('method', sa.String(), nullable=False),
        sa.Column('wrapped_cmk', sa.String(), nullable=False),
        sa.Column('salt', sa.String(), nullable=False),
        sa.Column('kdf_params_json', sa.String(), nullable=True),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.Float(), nullable=False),
        sa.ForeignKeyConstraint(['user_info_id'], ['userinfo.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_recovery_wrap_user_info_id'), 'recovery_wrap', ['user_info_id'])


def downgrade() -> None:
    op.drop_index(op.f('ix_recovery_wrap_user_info_id'), table_name='recovery_wrap')
    op.drop_table('recovery_wrap')
    op.drop_index(op.f('ix_device_key_user_info_id'), table_name='device_key')
    op.drop_table('device_key')
    with op.batch_alter_table('userinfo') as batch_op:
        batch_op.drop_column('encryption_enabled')
    with op.batch_alter_table('project') as batch_op:
        batch_op.drop_column('enc_version')
    with op.batch_alter_table('journalentry') as batch_op:
        batch_op.drop_column('enc_version')
    with op.batch_alter_table('memory') as batch_op:
        batch_op.drop_column('enc_version')
