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

from src.jobs.queue import ALL_QUEUES
from src.jobs.redis_client import get_redis, redis_url
from src.utils.logging import configure_logging, get_logger

_log = get_logger(__name__)


def main(argv: list[str] | None = None) -> int:
    """Consume the named queues (default: all) until killed."""
    configure_logging()
    os.environ.setdefault("VIEWTRIP_ROLE", "worker")

    queues = argv if argv else list(ALL_QUEUES)
    client = get_redis()
    if client is None:
        _log.error(
            "cannot start a worker: REDIS_URL is %s. Without a broker there is "
            "no queue to consume — the API process runs background work itself.",
            f"unreachable ({redis_url()})" if redis_url() else "not set")
        return 1

    from rq import Worker

    _log.info("worker starting on queues: %s", ", ".join(queues))
    Worker(queues, connection=client).work(with_scheduler=False)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
