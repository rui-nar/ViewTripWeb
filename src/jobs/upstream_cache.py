"""Shared cache for responses from a rate-limited upstream.

Companion to :mod:`src.jobs.upstream_slots`: that one paces requests we do make,
this one stops us making the same request twice.

Every Overpass query a resolve issues is a pure function of the segment's
coordinates, so a retry — a person tapping "retry", or
``sweep_degraded_segments`` re-attempting a degraded route — re-asks byte-for-
byte identical questions. Nothing cached them. On 2026-09-06 that repetition,
together with an hourly sweep that never terminated, earned this deployment's
IPv4 address an outright block from overpass-api.de: soft 429s first, then 504s,
then TCP refusals from both backends within about two minutes.

Cached in Redis so both workers and the API process share one copy, gzipped
because OSM geometry is extremely compressible (a multi-megabyte way dump is
mostly repeated coordinate digits), and with a size ceiling so one enormous
answer cannot crowd out the RQ queues that live in the same 256 MB broker.

Best-effort throughout: a cache that cannot answer must never be the reason a
resolve fails, so every failure path falls through to the live request.
"""
from __future__ import annotations

import gzip
import hashlib
from typing import Optional

from src.jobs.redis_client import get_redis
from src.utils.logging import get_logger

_log = get_logger(__name__)

# A day. Long enough to cover every repeat we actually make — a person retrying
# within minutes, and sweep_degraded_segments' five hourly attempts — without
# pinning a wrong answer for a week when someone fixes the underlying OSM data.
DEFAULT_TTL_S = 24 * 3600

# Ceiling on a single *compressed* entry. Overpass answers range from a few
# hundred bytes (a station lookup) to several megabytes (a bounding-box way
# dump); the large ones are both the most valuable to cache and the most
# expensive to store, so they are kept, but only up to a point.
DEFAULT_MAX_BYTES = 1_000_000


def _key(namespace: str, key_material: str) -> str:
    digest = hashlib.sha256(key_material.encode("utf-8")).hexdigest()
    return f"cache:{namespace}:{digest}"


def get(namespace: str, key_material: str) -> Optional[bytes]:
    """The cached body for *key_material*, or None on a miss or any failure."""
    client = get_redis()
    if client is None:
        return None
    try:
        blob = client.get(_key(namespace, key_material))
        return gzip.decompress(blob) if blob else None
    except Exception:  # noqa: BLE001 — a broken cache is a miss, never an error
        _log.warning("upstream cache read failed for %r", namespace)
        return None


def put(
    namespace: str,
    key_material: str,
    body: bytes,
    *,
    ttl_s: int = DEFAULT_TTL_S,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> bool:
    """Cache *body*. Returns whether it was stored (False if too big, or on error)."""
    client = get_redis()
    if client is None:
        return False
    try:
        blob = gzip.compress(body, compresslevel=6)
        if len(blob) > max_bytes:
            _log.info(
                "upstream response not cached: %d bytes compressed exceeds the "
                "%d byte ceiling", len(blob), max_bytes)
            return False
        client.setex(_key(namespace, key_material), ttl_s, blob)
        return True
    except Exception:  # noqa: BLE001 — failing to cache must not fail the request
        _log.warning("upstream cache write failed for %r", namespace)
        return False
