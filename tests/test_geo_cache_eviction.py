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


# ── Byte budget (issue #276) ─────────────────────────────────────────────────
#
# An entry count was never a real bound here: entries are whole gzipped project
# payloads and are wildly non-uniform. A 180-day trip's full details payload is
# ~35 MB of JSON before compression, so 200 of those is gigabytes in a
# container the deployment caps at 768 MB. Issue #276 saw both large requests
# for one trip fail after ~5 s while smaller payloads on the same project
# succeeded — what an OOM-killed container looks like from the client side.


def _store_sized(key: tuple, size: int) -> None:
    _geo_cache_store(key, b"x" * size, 0)


def test_total_bytes_are_bounded(monkeypatch):
    monkeypatch.setattr(geo_mod, "_GEO_CACHE_MAX_BYTES", 1000)
    monkeypatch.setattr(geo_mod, "_GEO_CACHE_MAX_ENTRY_BYTES", 10_000)
    for i in range(20):
        _store_sized((1, f"p{i}", False), 200)
    total = sum(len(v[0]) for v in _geo_cache.values())
    assert total <= 1000, f"cache held {total} bytes, over its budget"
    assert _geo_cache, "the budget must not empty the cache entirely"


def test_a_payload_too_large_is_never_cached(monkeypatch):
    monkeypatch.setattr(geo_mod, "_GEO_CACHE_MAX_ENTRY_BYTES", 100)
    _store_sized((1, "huge", False), 500)
    assert (1, "huge", False) not in _geo_cache


def test_an_oversized_write_evicts_its_own_stale_entry(monkeypatch):
    # A project that shrank below the limit and grew back over it must not
    # leave the old, now-wrong payload behind to be served as a HIT.
    monkeypatch.setattr(geo_mod, "_GEO_CACHE_MAX_ENTRY_BYTES", 100)
    _store_sized((1, "p", False), 50)
    assert (1, "p", False) in _geo_cache
    _store_sized((1, "p", False), 500)
    assert (1, "p", False) not in _geo_cache


def test_eviction_prefers_the_entry_closest_to_expiry(monkeypatch):
    monkeypatch.setattr(geo_mod, "_GEO_CACHE_MAX_BYTES", 400)
    monkeypatch.setattr(geo_mod, "_GEO_CACHE_MAX_ENTRY_BYTES", 10_000)
    _store_sized((1, "old", False), 200)
    # A later write has a later deadline, so the earlier one goes first.
    _store_sized((1, "new", False), 200)
    _store_sized((1, "newest", False), 200)
    assert (1, "old", False) not in _geo_cache
    assert (1, "newest", False) in _geo_cache
