"""Database engine and session factory — replaces rx.session()."""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

_DB_URL = os.environ.get("DATABASE_URL", "sqlite:///viewtripweb.db")
engine = create_engine(_DB_URL, connect_args={"check_same_thread": False})


def _configure_sqlite(target_engine) -> None:
    """Tune SQLite for concurrent access.

    Without this, SQLite runs with journal_mode=DELETE (writers block all
    readers) and busy_timeout=0 — so the moment two operations contend (e.g. a
    Polarsteps import firing parallel create_memory writes plus background photo
    downloads), it raises "database is locked" instead of waiting. On every new
    connection we set:

      * busy_timeout=30000 — wait up to 30s for a lock rather than erroring
        immediately. The single biggest win; safe on every filesystem.
      * journal_mode=WAL    — readers no longer block on the writer. Persisted in
        the DB header; safe on local filesystems (incl. Btrfs).
      * synchronous=NORMAL  — the standard, durable-enough pairing with WAL.

    No-op for non-SQLite backends.
    """
    if target_engine.dialect.name != "sqlite":
        return

    @event.listens_for(target_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn, _conn_record):  # pragma: no cover - thin
        cursor = dbapi_conn.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
        finally:
            cursor.close()


_configure_sqlite(engine)


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session():
    """Context manager that yields a SQLModel session — mirrors rx.session()."""
    with Session(engine) as session:
        yield session
