"""Cross-process geo cache invalidation (issue #173, phase B1).

The full-res GeoJSON cache is process-local: gzipped bytes in a dict. Once route
resolution runs in a worker process, that worker's ``bust_geo_cache`` drops only
*its own* copy — the API process would keep serving pre-resolve geometry until
the 300 s TTL expired. Silent staleness, strictly worse than the recompute the
cache exists to avoid.

The fix is a generation counter in Redis: each cached entry records the
generation it was computed against, and a read that no longer matches is a MISS.

"Two processes" here means two independently loaded copies of ``api.geo``, each
with its own ``_geo_cache``/``_geo_gen`` dicts, sharing one fake Redis. Note
``importlib.reload`` will not do — it mutates the existing module in place, so
both names would point at one cache and the test would prove nothing.
"""
from __future__ import annotations

import importlib.util

import fakeredis
import pytest

import src.jobs.redis_client as redis_client


@pytest.fixture
def shared_redis(monkeypatch):
    """One fake Redis server, reachable from every loaded copy of api.geo."""
    server = fakeredis.FakeServer()
    monkeypatch.setenv("REDIS_URL", "redis://fake")

    def _fake_get_redis():
        return fakeredis.FakeStrictRedis(server=server)

    monkeypatch.setattr(redis_client, "get_redis", _fake_get_redis)
    return _fake_get_redis


def _load_geo(get_redis=None):
    """Load a fresh, independent copy of api.geo — one simulated process."""
    import api.geo

    spec = importlib.util.spec_from_file_location("api.geo._proc", api.geo.__file__)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if get_redis is not None:
        mod.get_redis = get_redis
    return mod


KEY = (1, "Trip", False)


def _cache(proc, key=KEY, payload=b"payload"):
    """Populate *proc*'s cache the way a real read would."""
    proc._geo_cache_store(key, payload, proc._geo_generation(key[0], key[1]))


class TestTwoProcessesShareInvalidation:
    def test_the_processes_really_are_independent(self, shared_redis):
        """Guard the harness itself: separate caches, or the suite proves nothing."""
        a, b = _load_geo(shared_redis), _load_geo(shared_redis)
        assert a is not b
        assert a._geo_cache is not b._geo_cache

    def test_a_bust_in_one_process_invalidates_the_other(self, shared_redis):
        a, b = _load_geo(shared_redis), _load_geo(shared_redis)
        _cache(a)
        assert a._geo_cache_get(KEY) == b"payload"

        b.bust_geo_cache(1, "Trip")   # e.g. a resolve finishing in the worker

        assert a._geo_cache_get(KEY) is None, (
            "process A kept serving a payload another process invalidated")

    def test_an_unrelated_project_is_not_invalidated(self, shared_redis):
        a, b = _load_geo(shared_redis), _load_geo(shared_redis)
        _cache(a)

        b.bust_geo_cache(1, "Other Trip")

        assert a._geo_cache_get(KEY) == b"payload"

    def test_the_counter_is_per_user(self, shared_redis):
        a, b = _load_geo(shared_redis), _load_geo(shared_redis)
        _cache(a)

        b.bust_geo_cache(2, "Trip")   # same project name, different owner

        assert a._geo_cache_get(KEY) == b"payload"

    def test_a_store_racing_a_remote_bust_is_declined(self, shared_redis):
        """The pre-existing generation guard (#132) must also see remote busts."""
        a, b = _load_geo(shared_redis), _load_geo(shared_redis)
        gen = a._geo_generation(1, "Trip")    # captured before the DB read

        b.bust_geo_cache(1, "Trip")           # lands while A is still reading

        a._geo_cache_store(KEY, b"computed-from-stale-read", gen)
        assert a._geo_cache_get(KEY) is None


class TestWithoutRedis:
    """No broker → the local counter is the authority, exactly as before."""

    def test_local_bust_still_invalidates(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)
        redis_client.reset_redis()
        geo = _load_geo()

        _cache(geo)
        assert geo._geo_cache_get(KEY) == b"payload"
        geo.bust_geo_cache(1, "Trip")
        assert geo._geo_cache_get(KEY) is None

    def test_two_processes_do_not_share_invalidation_without_a_broker(self, monkeypatch):
        """Documents the limit: cross-process invalidation *needs* the broker.

        This is why REDIS_URL is a prerequisite for running jobs out of process
        (phase B), not merely an optimisation.
        """
        monkeypatch.delenv("REDIS_URL", raising=False)
        redis_client.reset_redis()
        a, b = _load_geo(), _load_geo()

        _cache(a)
        b.bust_geo_cache(1, "Trip")

        assert a._geo_cache_get(KEY) == b"payload"  # A never hears about it

    def test_an_unreachable_broker_falls_back_instead_of_raising(self, monkeypatch):
        """A configured-but-down Redis must degrade, not break geo requests."""
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1")  # nothing listening
        redis_client.reset_redis()
        try:
            geo = _load_geo()
            _cache(geo)                       # must not raise
            assert geo._geo_cache_get(KEY) == b"payload"
            geo.bust_geo_cache(1, "Trip")     # must not raise
            assert geo._geo_cache_get(KEY) is None
        finally:
            redis_client.reset_redis()
