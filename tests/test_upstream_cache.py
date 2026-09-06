"""Tests for the shared upstream response cache (src.jobs.upstream_cache).

Its job is to stop us re-asking a rate-limited service a question we already
have the answer to. On 2026-09-06 that repetition — a person retrying, plus an
hourly sweep that never terminated — cost this deployment's IPv4 address an
outright block from overpass-api.de, so "does a second identical call reach the
network" is the behaviour under test, not an optimisation detail.
"""

import gzip

import fakeredis
import pytest

from src.jobs import upstream_cache
from src.jobs.upstream_cache import get, put


@pytest.fixture
def redis(monkeypatch):
    client = fakeredis.FakeRedis()
    monkeypatch.setattr(upstream_cache, "get_redis", lambda: client)
    return client


class TestRoundTrip:
    def test_stores_and_returns_the_body(self, redis):
        assert put("overpass", "query A", b'{"elements": []}') is True
        assert get("overpass", "query A") == b'{"elements": []}'

    def test_a_different_query_is_a_miss(self, redis):
        put("overpass", "query A", b"one")
        assert get("overpass", "query B") is None

    def test_namespaces_are_independent(self, redis):
        put("overpass", "same", b"one")
        assert get("other", "same") is None

    def test_body_is_stored_compressed(self, redis):
        """OSM geometry is mostly repeated coordinate digits, and this cache
        shares a 256 MB broker with the RQ queues — storing it raw would be the
        difference between fitting and evicting someone's queued job."""
        body = b'{"elements": [' + b'{"lat": 51.5, "lon": 0.1},' * 500 + b"]}"
        put("overpass", "big", body)

        stored = redis.get(list(redis.scan_iter("cache:overpass:*"))[0])
        assert len(stored) < len(body) / 5
        assert gzip.decompress(stored) == body

    def test_entries_expire(self, redis):
        put("overpass", "query A", b"one", ttl_s=99)
        key = list(redis.scan_iter("cache:overpass:*"))[0]
        assert 0 < redis.ttl(key) <= 99


class TestSizeCeiling:
    def test_an_oversized_entry_is_skipped(self, redis):
        """One enormous answer must not crowd out the queue data sharing this
        broker. Skipped, not truncated — half an answer is worse than none."""
        incompressible = bytes(range(256)) * 8000  # ~2 MB, gzip-resistant
        assert put("overpass", "huge", incompressible, max_bytes=1000) is False
        assert get("overpass", "huge") is None

    def test_the_ceiling_is_measured_after_compression(self, redis):
        """A megabyte of repetitive JSON costs kilobytes to store, so judging it
        on its raw size would refuse exactly the entries most worth keeping."""
        compressible = b'{"lat": 51.5, "lon": 0.1},' * 40_000  # ~1 MB raw
        assert put("overpass", "repetitive", compressible, max_bytes=100_000) is True


class TestDegradedModes:
    def test_no_broker_is_a_miss_not_an_error(self, monkeypatch):
        monkeypatch.setattr(upstream_cache, "get_redis", lambda: None)
        assert put("overpass", "q", b"body") is False
        assert get("overpass", "q") is None

    @pytest.mark.parametrize("operation", ["read", "write"])
    def test_a_broken_broker_falls_through(self, monkeypatch, operation):
        """A cache that cannot answer is a miss. It must never be the reason a
        resolve fails — the live request is always still available."""
        class _Broken:
            def __getattr__(self, _name):
                def _raise(*_a, **_kw):
                    raise ConnectionError("broker down")
                return _raise

        monkeypatch.setattr(upstream_cache, "get_redis", lambda: _Broken())
        if operation == "read":
            assert get("overpass", "q") is None
        else:
            assert put("overpass", "q", b"body") is False
