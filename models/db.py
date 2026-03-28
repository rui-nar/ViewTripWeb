"""Database engine and session factory — replaces rx.session()."""
from __future__ import annotations

import os
from contextlib import contextmanager

from sqlmodel import Session, SQLModel, create_engine

_DB_URL = os.environ.get("DATABASE_URL", "sqlite:///viewtripweb.db")
engine = create_engine(_DB_URL, connect_args={"check_same_thread": False})


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session():
    """Context manager that yields a SQLModel session — mirrors rx.session()."""
    with Session(engine) as session:
        yield session
