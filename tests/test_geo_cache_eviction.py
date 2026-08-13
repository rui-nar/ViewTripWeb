"""``_geo_cache`` must not grow without bound (issue #209, third incident).

The TTL in ``_geo_cache_get`` only turns a stale HIT into a MISS for a key that
gets *read* again. A project nobody revisits (and nobody mutates, so it's never
busted either) just sits in the dict forever. With enough distinct
(user, project, variant) combinations touched over an API process's uptime,
that is unbounded growth — the process was OOM-killed on ordinary traffic with
no single heavy request to blame. ``_geo_cache_store`` now sweeps expired
entries and enforces a hard cap on every write.
"""
from __future__ import annotations

import pytest

import api.geo as geo_mod
from api.geo import _geo_cache, _geo_cache_store, _geo_gen


@pytest.fixture(autouse=True)
def _clear():
    _geo_cache.clear()
    _geo_gen.clear()
    yield
    _geo_cache.clear()
    _geo_gen.clear()


def _store(key: tuple, monkeypatch=None) -> None:
    _geo_cache_store(key, b"payload", 0)


def test_store_sweeps_already_expired_entries(monkeypatch):
    clock = {"now": 1_000.0}
    monkeypatch.setattr(geo_mod, "monotonic", lambda: clock["now"])

    _store((1, "Trip", False))
    clock["now"] += geo_mod._GEO_CACHE_TTL_S + 1  # the entry above is now stale

    _store((2, "OtherTrip", False))

    assert (1, "Trip", False) not in _geo_cache, "an expired entry must not linger"
    assert (2, "OtherTrip", False) in _geo_cache


def test_store_caps_total_entries(monkeypatch):
    clock = {"now": 1_000.0}
    monkeypatch.setattr(geo_mod, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(geo_mod, "_GEO_CACHE_MAX_ENTRIES", 3)

    for i in range(3):
        clock["now"] += 1  # distinct deadlines so eviction order is deterministic
        _store((i, "Trip", False))
    assert len(_geo_cache) == 3

    clock["now"] += 1
    _store((99, "NewTrip", False))

    assert len(_geo_cache) == 3, "must not grow past the cap"
    assert (99, "NewTrip", False) in _geo_cache, "the new entry must be kept"
    assert (0, "Trip", False) not in _geo_cache, "the soonest-to-expire entry is evicted first"
    assert (1, "Trip", False) in _geo_cache
    assert (2, "Trip", False) in _geo_cache


def test_overwriting_an_existing_key_does_not_evict(monkeypatch):
    """Refreshing a key already in the cache must not count as growth."""
    clock = {"now": 1_000.0}
    monkeypatch.setattr(geo_mod, "monotonic", lambda: clock["now"])
    monkeypatch.setattr(geo_mod, "_GEO_CACHE_MAX_ENTRIES", 2)

    _store((1, "Trip", False))
    clock["now"] += 1
    _store((2, "Trip", False))
    assert len(_geo_cache) == 2

    clock["now"] += 1
    _store((1, "Trip", False))  # refresh, not a new key

    assert len(_geo_cache) == 2
    assert (1, "Trip", False) in _geo_cache
    assert (2, "Trip", False) in _geo_cache
