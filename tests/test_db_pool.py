"""Regression tests for DB connection-pool sizing (issue #35).

Production hung with `QueuePool limit of size 5 overflow 10 reached, connection
timed out` — the default pool was far too small for the Flutter client's
parallel request fan-out, and once exhausted every request blocked for 30s so
the app needed a manual restart. These tests pin the fix:
  1. file-backed engines get a pool comfortably larger than the old 15;
  2. connections are returned to the pool (no leak that would re-exhaust it).
"""
from sqlalchemy import text

from models.db import _make_engine


def test_file_sqlite_pool_is_sized_for_concurrency(tmp_path):
    eng = _make_engine(f"sqlite:///{(tmp_path / 'pool.db').as_posix()}")
    # 20 persistent + 40 overflow = 60 total, well above the old 15 that hung.
    assert eng.pool.size() == 20
    assert eng.pool._max_overflow == 40
    total_capacity = eng.pool.size() + eng.pool._max_overflow
    assert total_capacity >= 30


def test_connections_are_returned_to_the_pool(tmp_path):
    """No leak: after many acquire/release cycles nothing stays checked out."""
    eng = _make_engine(f"sqlite:///{(tmp_path / 'leak.db').as_posix()}")
    for _ in range(50):
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
    assert eng.pool.checkedout() == 0


def test_in_memory_engine_still_builds(tmp_path):
    """The in-memory pool rejects QueuePool kwargs; the guard must skip them."""
    eng = _make_engine("sqlite://")
    with eng.connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1
