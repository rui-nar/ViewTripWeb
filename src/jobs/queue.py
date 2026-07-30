"""RQ queues and the enqueue helpers every background job goes through (#173).

Before this, background work ran as FastAPI ``BackgroundTasks`` in the API
process. That has two problems the queue fixes:

* **Durability.** A restart loses every in-flight job. For route resolution the
  segment stayed ``pending`` and recovery was implemented in the Flutter client,
  which only ran when someone reopened the project.
* **Concurrency control.** Overpass rate-limits per IP, and unbounded parallel
  resolves collided on it. An RQ worker runs one job at a time, so the bound is
  the worker count for the ``resolve`` queue — a deployment parameter, enforced
  regardless of how many API processes exist. A ``threading`` semaphore could
  not do this: it only ever bounded one process.

``enqueue`` falls back to running in-process when no broker is configured, so a
self-hosted instance and the test suite need no Redis. That fallback is also the
rollback lever: unset ``REDIS_URL`` and the deployment reverts to the old
behaviour with no image change.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from src.jobs.redis_client import get_redis
from src.utils.logging import get_logger

_log = get_logger(__name__)

# Queue names. Split by workload profile rather than by feature: what matters is
# how many may run at once and how long each holds a worker.
QUEUE_RESOLVE = "resolve"   # HAFAS + Overpass; the count here is the OSM bound
QUEUE_POSTER = "poster"     # A0 rendering — memory-heavy, keep it to one
QUEUE_DEFAULT = "default"   # share tiles, stats: short and cheap

ALL_QUEUES = (QUEUE_RESOLVE, QUEUE_POSTER, QUEUE_DEFAULT)

# Generous: a rail resolve makes several Overpass queries, each with a 45 s HTTP
# timeout. Well past the point where the client has stopped polling, but the
# result is still worth persisting for the next page load.
_JOB_TIMEOUT_S = 600
_RESULT_TTL_S = 3600

# Retries are a queue property here rather than something each job hand-rolls.
# The intervals are minutes, not milliseconds: these failures are rate limits
# and network trouble, not write contention.
_RETRY_INTERVALS = [10, 30, 60]


def queue_available() -> bool:
    """Whether jobs will be queued rather than run in-process."""
    return get_redis() is not None


def get_queue(name: str):
    """The RQ queue *name*, or ``None`` when running without a broker."""
    client = get_redis()
    if client is None:
        return None
    from rq import Queue  # imported lazily: unused in the no-Redis deployment

    return Queue(name, connection=client, default_timeout=_JOB_TIMEOUT_S)


def enqueue(
    queue_name: str,
    func: Callable[..., Any],
    *args: Any,
    background_tasks: Optional[Any] = None,
    max_retries: int = len(_RETRY_INTERVALS),
    **kwargs: Any,
) -> bool:
    """Run *func* out of process if possible; otherwise in this one.

    Returns True when the job was queued. Pass *background_tasks* from a request
    handler so the fallback still defers the work until after the response —
    without it the fallback runs *inline*, which for a resolve would block the
    request for the tens of seconds this whole design exists to avoid.

    A broker that fails at enqueue time falls back rather than 500s: losing
    durability is better than losing the request.
    """
    queue = get_queue(queue_name)
    if queue is not None:
        try:
            from rq import Retry

            queue.enqueue(
                func, *args,
                retry=Retry(max=max_retries, interval=_RETRY_INTERVALS[:max_retries]),
                result_ttl=_RESULT_TTL_S,
                **kwargs,
            )
            return True
        except Exception as exc:  # noqa: BLE001 — degrade to in-process
            _log.warning("enqueue to %r failed (%s) — running in-process", queue_name, exc)

    if background_tasks is not None:
        background_tasks.add_task(func, *args, **kwargs)
    else:
        func(*args, **kwargs)
    return False
