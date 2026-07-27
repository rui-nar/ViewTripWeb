"""The #110 migration's data backfill (revision c8f1a2b3d4e5).

Runs the real migration against a scratch SQLite file seeded with rows shaped
like pre-#110 production data, because the interesting part of this revision is
the two UPDATE statements, not the DDL — and a backfill that silently does
nothing looks identical to a correct one until an invite fails to match.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

_REPO = Path(__file__).resolve().parents[1]
_TARGET = "c8f1a2b3d4e5"
_PREVIOUS = "f68e7e215b0f"


def _alembic(db_path: Path, *args: str) -> None:
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_REPO,
        # Extend the real environment rather than replacing it — a bare env
        # breaks socket initialisation on Windows before alembic even starts.
        env={**os.environ, "DATABASE_URL": f"sqlite:///{db_path.as_posix()}"},
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise AssertionError(f"alembic {' '.join(args)} failed:\n{result.stderr}")


def _seed_pre_110(db: Path) -> None:
    """Populate a DB at *_PREVIOUS* with the three account shapes that exist
    in the wild before #110."""
    engine = create_engine(f"sqlite:///{db.as_posix()}")
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO localuser (id, username, password_hash, enabled, "
            "password_change_required) VALUES "
            "(1, 'Local.User@Example.COM', X'00', 1, 0), "
            "(2, 'admin', X'00', 1, 0), "
            "(3, 'google_abc123', X'00', 1, 0)"))
        conn.execute(text(
            "INSERT INTO userinfo (id, local_auth_id, google_sub, display_name, "
            "email, avatar_url, auth_provider, is_admin, created_at, "
            "encryption_enabled) VALUES "
            # Local account: username is an address, email was discarded.
            "(1, 1, '', 'Local User', '', '', 'local', 0, 0.0, 0), "
            # Seeded admin: username is not an address at all.
            "(2, 2, '', 'admin', '', '', 'local', 1, 0.0, 0), "
            # Google account: already carries a real address.
            "(3, 3, 'abc123', 'Goog User', 'goog@example.com', '', 'google', "
            "0, 0.0, 0)"))
    engine.dispose()


@pytest.fixture(scope="module")
def migrated(tmp_path_factory):
    """A seeded DB upgraded through #110.

    Module-scoped and read-only for its consumers: running the whole revision
    chain in a subprocess costs ~12s, and every assertion here inspects the
    same post-migration state.
    """
    db = tmp_path_factory.mktemp("mig") / "backfill.db"
    _alembic(db, "upgrade", _PREVIOUS)
    _seed_pre_110(db)
    _alembic(db, "upgrade", _TARGET)
    return create_engine(f"sqlite:///{db.as_posix()}")


def _row(engine, user_id):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT email, email_verified FROM userinfo WHERE id = :i"
        ), {"i": user_id}).one()


class TestEmailBackfill:
    def test_local_username_recovered_as_email_lowercased(self, migrated):
        email, _ = _row(migrated, 1)
        assert email == "local.user@example.com"

    def test_non_email_username_left_alone(self, migrated):
        """The seeded admin's username is "admin" — not an address. Copying it
        into the email column would produce an account that looks reachable
        and is not."""
        email, _ = _row(migrated, 2)
        assert email == ""

    def test_existing_email_not_overwritten(self, migrated):
        email, _ = _row(migrated, 3)
        assert email == "goog@example.com"


class TestVerifiedBackfill:
    def test_google_accounts_are_verified(self, migrated):
        _, verified = _row(migrated, 3)
        assert verified == 1

    def test_local_accounts_are_not_verified(self, migrated):
        """Nothing ever checked that a local account's address was real —
        which is the hole the verification gate exists to close."""
        _, verified = _row(migrated, 1)
        assert verified == 0

    def test_emailless_account_is_not_verified(self, migrated):
        _, verified = _row(migrated, 2)
        assert verified == 0


class TestReversible:
    def test_downgrade_drops_tables_and_column(self, tmp_path):
        """Own DB — this mutates schema, and the shared fixture is read-only."""
        db = tmp_path / "reversible.db"
        _alembic(db, "upgrade", _TARGET)
        _alembic(db, "downgrade", _PREVIOUS)

        engine = create_engine(f"sqlite:///{db.as_posix()}")
        with engine.connect() as conn:
            tables = {r[0] for r in conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table'"))}
            columns = {r[1] for r in conn.execute(text(
                "PRAGMA table_info(userinfo)"))}
        engine.dispose()

        assert "projectpendinginvite" not in tables
        assert "emailverification" not in tables
        assert "email_verified" not in columns

        # Re-applying must succeed, or a rolled-back deploy can never roll forward.
        _alembic(db, "upgrade", _TARGET)
