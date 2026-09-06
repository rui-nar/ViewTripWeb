"""Cross-process pacing state for a rate-limited upstream host.

Two things live here: a cap on concurrent in-flight requests, and a cooldown
marking a host as "do not talk to for N seconds" after it has told us to back
off. Both are shared through Redis so every worker honours them, and both fall
back to process-local state when there is no broker — a deployment without one
runs a single process, so local state is the whole truth there.

Distinct from ``src.utils.rate_limit.KeyedRateLimiter``, and deliberately so:
that one bounds an *event rate* (N per sliding window) per key in a single
process and refuses immediately, which is right for "you have sent too many
invites". This one bounds *concurrency* (N in flight) on a host, across
processes, and waits — right for an upstream quota, where the work still has
to happen.

Overpass advertises a per-IP concurrency cap (``Rate limit: 2`` on
overpass-api.de). Before this, the only thing bounding our request rate was the
number of RQ workers listening on ``resolve`` — which is the wrong lever twice
over: one rail resolve issues four or five Overpass queries, and jobs on the
other queues issue none, so a worker count cannot express "at most N requests
in flight". Two workers running two resolves therefore sat exactly on the cap
with no headroom, and every collision came back as a 429.

Implemented as a Redis sorted set of leases scored by acquisition time. A
holder claims optimistically and then checks its own rank: only the lowest
*limit* ranks keep their lease, so two processes racing cannot both conclude
they hold the last slot. A holder that dies without releasing is reclaimed once
its lease ages out, so a crashed worker cannot consume a slot permanently.

With no Redis configured this is a no-op — the same degraded-but-coherent mode
as the rest of ``src.jobs``: no broker means no worker, so only one process is
making requests and there is nothing to coordinate.
"""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from typing import Iterator

from src.jobs.redis_client import get_redis
from src.utils.logging import get_logger

_log = get_logger(__name__)

# How often to re-check for a free slot while waiting. Short enough to pick up a
# slot freed by a fast query promptly, long enough not to spin on the broker.
_POLL_INTERVAL_S = 0.25


@contextmanager
def slot(
    name: str, limit: int, *, timeout_s: float, lease_ttl_s: float,
) -> Iterator[bool]:
    """Hold one of *limit* concurrent slots for *name*, or report failure.

    Yields True when a slot is held (released on exit) and False when none came
    free within *timeout_s* — the caller decides what to do about it, because
    "wait longer" and "try a different host" are both reasonable and only the
    caller knows which is cheaper.

    Yields True *without* holding anything when there is no broker, or when the
    broker errors: this paces a request, it does not authorise it, so a limiter
    that cannot answer must not be the reason work stops.
    """
    client = get_redis()
    if client is None or limit <= 0:
        yield True
        return

    key = f"ratelimit:{name}"
    token = uuid.uuid4().hex
    deadline = time.monotonic() + timeout_s
    acquired = False
    unpaced = False

    while True:
        try:
            now = time.time()
            # Reclaim leases from holders that died without releasing.
            client.zremrangebyscore(key, "-inf", now - lease_ttl_s)
            # Claim first, then check rank: two processes racing here both add
            # themselves and then agree on who won, where a check-then-add
            # would let both see a free slot and overshoot the cap.
            client.zadd(key, {token: now})
            client.expire(key, int(lease_ttl_s) + 1)
            rank = client.zrank(key, token)
            if rank is not None and rank < limit:
                acquired = True
            else:
                client.zrem(key, token)
        except Exception as exc:  # noqa: BLE001 — pacing must not block the work
            _log.warning(
                "rate limiter unavailable for %r (%s) — proceeding unpaced", name, exc)
            unpaced = True

        if acquired or unpaced or time.monotonic() >= deadline:
            break
        time.sleep(_POLL_INTERVAL_S)

    try:
        yield acquired or unpaced
    finally:
        if acquired:
            try:
                client.zrem(key, token)
            except Exception:  # noqa: BLE001 — the lease ages out on its own
                _log.warning("could not release rate-limit slot for %r", name)


# ── Cooldowns ─────────────────────────────────────────────────────────────────
#
# overpass-api.de's policy is "if you receive an HTTP error code such as 429 or
# 406, pause for 30 seconds before making a new request", and the operators have
# said plainly that clients which repeatedly hit a 429 get banned faster — a high
# 429 *rate* is itself a trigger, independently of how fast you retry.
#
# The unit that matters is therefore the host, not the request: waiting inside one
# query while the next query in the same resolve immediately hits the same host
# would honour the letter and miss the point. Marking the host instead makes one
# back-off apply to every query from every worker.

_local_cooldowns: dict[str, float] = {}


def mark_cooling(name: str, seconds: float) -> None:
    """Refuse *name* for *seconds*. Never raises."""
    until = time.time() + seconds
    _local_cooldowns[name] = until
    client = get_redis()
    if client is None:
        return
    try:
        client.setex(f"cooldown:{name}", int(seconds) + 1, str(until))
    except Exception:  # noqa: BLE001 — the local copy still covers this process
        _log.warning("could not publish a cooldown for %r", name)


def is_cooling(name: str) -> bool:
    """Whether *name* is still backing off. False on any doubt, so a broken
    broker cannot silently disable an upstream we are allowed to use."""
    if _local_cooldowns.get(name, 0.0) > time.time():
        return True
    client = get_redis()
    if client is None:
        return False
    try:
        return client.exists(f"cooldown:{name}") == 1
    except Exception:  # noqa: BLE001
        return False
