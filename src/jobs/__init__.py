"""Background job dispatch: Redis-backed queues with an in-process fallback.

See ``src/jobs/redis_client.py`` for the connection (and what happens without
one) and ``src/jobs/queue.py`` for the queues themselves.
"""
