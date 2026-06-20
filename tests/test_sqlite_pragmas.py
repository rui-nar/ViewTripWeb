"""SQLite is tuned for concurrent access (issue: "database is locked" storms).

Without busy_timeout/WAL, concurrent writes (e.g. a Polarsteps import firing
parallel create_memory + background photo writes) raise OperationalError
immediately instead of waiting. models.db._configure_sqlite must set those
PRAGMAs on every new connection.
"""
from sqlmodel import create_engine

from models.db import _configure_sqlite


def test_pragmas_applied_on_every_connection(tmp_path):
    db = tmp_path / "t.db"
    eng = create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})
    _configure_sqlite(eng)
    with eng.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 30000
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
        # synchronous: 1 == NORMAL
        assert conn.exec_driver_sql("PRAGMA synchronous").scalar() == 1
    eng.dispose()


def test_noop_for_non_sqlite_backend():
    class _FakeDialect:
        name = "postgresql"

    class _FakeEngine:
        dialect = _FakeDialect()

    # Must not raise and must not try to register a SQLite PRAGMA listener.
    _configure_sqlite(_FakeEngine())
