"""RQ worker entry point — ``python -m src.jobs.worker`` (issue #173).

Run one process per unit of concurrency you want. For the ``resolve`` queue that
count *is* the Overpass politeness bound, so raising it is a deliberate decision
about load on a free public API, not a throughput knob.

The worker deliberately does not run migrations, the APScheduler jobs, or the
admin seed — see ``VIEWTRIP_ROLE`` in ``api/router.py`` for why.
"""
from __future__ import annotations

import os
import sys
import time

from src.jobs.queue import ALL_QUEUES
from src.jobs.redis_client import get_redis, redis_url, reset_redis
from src.utils.logging import configure_logging, env_level, get_logger

_log = get_logger(__name__)

# Backoff between reconnect attempts once REDIS_URL is set but the broker isn't
# answering. Capped, not unbounded — a worker idling at a 60s ping is cheap to
# leave running.
#
# Previously a single failed probe made the worker exit(1) immediately, and
# `restart: unless-stopped` relaunched it a few seconds later. That is fine for
# a broker that is actually down, but when Redis is merely *slow* — starved by
# whatever else is loading the host — every relaunch itself burns CPU/memory,
# deepening the exact contention that made Redis slow in the first place. Two
# workers doing that in lockstep turned one overloaded host into a ~15s crash
# loop that outlasted the job that triggered it (issue #209). Retrying in place
# costs nothing extra and gives the underlying pressure a chance to clear.
_RECONNECT_INTERVALS_S = [2, 5, 10, 30, 60]


def _connect_with_retry(sleep=time.sleep):
    """Block until Redis answers, retrying with backoff instead of giving up."""
    attempt = 0
    while True:
        client = get_redis()
        if client is not None:
            return client
        delay = _RECONNECT_INTERVALS_S[min(attempt, len(_RECONNECT_INTERVALS_S) - 1)]
        _log.warning("Redis unreachable (%s) — retrying in %ss", redis_url(), delay)
        sleep(delay)
        reset_redis()
        attempt += 1


def main(argv: list[str] | None = None) -> int:
    """Consume the named queues (default: all) until killed."""
    # LOG_LEVEL (issue #208) is the restart-persistent baseline. A live admin
    # override applies on top of it per-job (see src.jobs.queue.enqueue).
    configure_logging(level=env_level())
    os.environ.setdefault("VIEWTRIP_ROLE", "worker")

    queues = argv if argv else list(ALL_QUEUES)

    if not redis_url():
        _log.error(
            "cannot start a worker: REDIS_URL is not set. Without a broker "
            "there is no queue to consume — the API process runs background "
            "work itself.")
        return 1

    client = _connect_with_retry()

    from rq import Worker

    _log.info("worker starting on queues: %s", ", ".join(queues))
    Worker(queues, connection=client).work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
