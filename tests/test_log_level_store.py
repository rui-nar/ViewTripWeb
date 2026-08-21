"""Redis-backed shared copy of the live log-level override (issue #208).

Mirrors tests/test_job_queue.py's fakeredis-broker pattern: this store is
optional infrastructure, only exercised when REDIS_URL is set, and must
degrade to a silent no-op everywhere else — the no-Redis deployment is the
supported default, not a degraded corner.
"""
from __future__ import annotations

import time

import fakeredis
import pytest

import src.jobs.redis_client as redis_client
import src.utils.log_level_store as store


@pytest.fixture(autouse=True)
def _clear():
    yield
    redis_client.reset_redis()


@pytest.fixture
def broker(monkeypatch):
    server = fakeredis.FakeServer()
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setattr(
        store, "get_redis", lambda: fakeredis.FakeStrictRedis(server=server)
    )
    return server


@pytest.fixture
def no_broker(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset_redis()


class TestWithoutABroker:
    def test_read_returns_none(self, no_broker):
        assert store.read() is None

    def test_write_is_a_silent_no_op(self, no_broker):
        store.write(10, None)  # must not raise
        assert store.read() is None

    def test_clear_is_a_silent_no_op(self, no_broker):
        store.clear()  # must not raise


class TestWithABroker:
    def test_round_trips_an_indefinite_override(self, broker):
        store.write(10, None)
        assert store.read() == (10, None)

    def test_round_trips_a_timed_override(self, broker):
        expires_at = time.time() + 900
        store.write(10, expires_at)
        level, read_expires_at = store.read()
        assert level == 10
        # Float round-trips through Redis as a string; allow sub-millisecond drift.
        assert read_expires_at == pytest.approx(expires_at)

    def test_clear_removes_the_entry(self, broker):
        store.write(10, None)
        store.clear()
        assert store.read() is None

    def test_a_write_expires_via_redis_ttl(self, broker):
        """Belt-and-suspenders: even if the admin API's own scheduled revert
        is lost, Redis itself drops the key once its TTL elapses."""
        store.write(10, time.time() + 1)
        client = store.get_redis()
        ttl = client.ttl(store._KEY)
        assert 0 < ttl <= 1

    def test_an_indefinite_override_has_no_ttl(self, broker):
        store.write(10, None)
        client = store.get_redis()
        assert client.ttl(store._KEY) == -1
