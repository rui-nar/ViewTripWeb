"""Redis connection, with a working no-Redis mode (issue #173).

Redis is optional on purpose. This project is self-hostable and its test suite
must not require a broker, so everything that uses Redis has to keep working
without one — background work falls back to FastAPI ``BackgroundTasks`` in the
API process, exactly as it behaved before phase C.

That is also the rollback lever: unset ``REDIS_URL`` and the deployment reverts
to single-process behaviour with no image change.

A configured-but-unreachable Redis degrades the same way rather than failing
requests. The degraded mode is coherent, not merely safe: with no reachable
broker no worker can be running either, so all background work is back in the
API process and the process-local caches it invalidates are once again the only
ones that exist.
"""
from __future__ import annotations

import os
import threading
from typing import Optional

from src.utils.logging import get_logger

_log = get_logger(__name__)

# Short: a broker that cannot answer promptly must not hold up a request. The
# caller's fallback path is always correct, just less efficient.
_CONNECT_TIMEOUT_S = 2.0

_lock = threading.Lock()
_client = None            # cached redis.Redis
_probed = False           # whether we have tried to connect since the last reset
_warned = False           # log an unreachable broker once, not per call


def redis_url() -> str:
    """The configured broker URL, or "" when Redis is not in use."""
    return os.environ.get("REDIS_URL", "").strip()


def get_redis():
    """A live Redis client, or ``None`` when unset/unreachable.

    Callers must treat ``None`` as "run in-process" rather than an error. The
    connection is probed once and cached; a broker that goes away later surfaces
    as an exception at the call site, which callers wrap in the same fallback.
    """
    global _client, _probed, _warned

    url = redis_url()
    if not url:
        return None

    with _lock:
        if _probed:
            return _client
        _probed = True
        try:
            import redis  # imported lazily: unused in the no-Redis deployment

            client = redis.Redis.from_url(
                url,
                socket_connect_timeout=_CONNECT_TIMEOUT_S,
                socket_timeout=_CONNECT_TIMEOUT_S,
                health_check_interval=30,
            )
            client.ping()
            _client = client
            _log.info("Redis connected (%s) — background jobs will be queued", url)
        except Exception as exc:  # noqa: BLE001 — any failure means "no broker"
            if not _warned:
                _warned = True
                _log.warning(
                    "REDIS_URL is set but Redis is unreachable (%s) — falling back "
                    "to in-process background tasks", exc)
            _client = None
        return _client


def reset_redis() -> None:
    """Drop the cached client so the next call re-probes. For tests."""
    global _client, _probed, _warned
    with _lock:
        _client = None
        _probed = False
        _warned = False
