"""Job dispatch: RQ when a broker is configured, in-process when not (#173).

The no-broker path is not a degraded corner — it is the supported configuration
for a self-hosted instance and for this test suite, and it is the rollback lever
for the deployment (unset REDIS_URL, no image change). So it gets the same
coverage as the queued path.
"""
from __future__ import annotations

import fakeredis
import pytest

import src.jobs.queue as queue_mod
import src.jobs.redis_client as redis_client
from src.jobs.queue import (
    QUEUE_DEFAULT,
    QUEUE_POSTER,
    QUEUE_RESOLVE,
    enqueue,
    queue_available,
)


_calls: list = []


def _record(*args, **kwargs):
    """Module-level so RQ can import it by reference when queued."""
    _calls.append((args, kwargs))


class _FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, func, *args, **kwargs):
        self.tasks.append((func, args, kwargs))


@pytest.fixture(autouse=True)
def _clear():
    _calls.clear()
    yield
    _calls.clear()
    redis_client.reset_redis()


@pytest.fixture
def broker(monkeypatch):
    """A fake Redis wired in as the queue's connection."""
    server = fakeredis.FakeServer()
    monkeypatch.setenv("REDIS_URL", "redis://fake")
    monkeypatch.setattr(
        queue_mod, "get_redis", lambda: fakeredis.FakeStrictRedis(server=server))
    return server


@pytest.fixture
def no_broker(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    redis_client.reset_redis()


class TestWithoutABroker:
    def test_queue_is_reported_unavailable(self, no_broker):
        assert queue_available() is False

    def test_work_is_deferred_to_background_tasks(self, no_broker):
        bg = _FakeBackgroundTasks()
        queued = enqueue(QUEUE_RESOLVE, _record, 1, "x", background_tasks=bg)

        assert queued is False
        assert _calls == [], "must not run inline while the request is still open"
        assert len(bg.tasks) == 1
        func, args, _ = bg.tasks[0]
        func(*args)
        assert _calls == [((1, "x"), {})]

    def test_without_background_tasks_it_runs_inline(self, no_broker):
        """The only remaining option — used by callers outside a request."""
        assert enqueue(QUEUE_RESOLVE, _record, 7) is False
        assert _calls == [((7,), {})]


class TestWithABroker:
    def test_queue_is_reported_available(self, broker):
        assert queue_available() is True

    def test_the_job_is_queued_not_run(self, broker):
        bg = _FakeBackgroundTasks()
        queued = enqueue(QUEUE_RESOLVE, _record, 1, "x", background_tasks=bg)

        assert queued is True
        assert _calls == [], "queued work must not also run in this process"
        assert bg.tasks == [], "queued work must not also be a background task"

    def test_the_job_lands_on_the_right_queue_and_survives_a_restart(self, broker):
        """The job is durable state in Redis, not a reference in this process."""
        enqueue(QUEUE_RESOLVE, _record, 42)

        q = queue_mod.get_queue(QUEUE_RESOLVE)
        assert q.count == 1
        job = q.jobs[0]
        # Wrapped in _run_with_level_refresh (issue #208) so the worker
        # refreshes its log level from the shared store before running the
        # real job — the queued callable is the wrapper, not _record itself.
        assert job.func is queue_mod._run_with_level_refresh
        assert job.args == (_record, 42)
        assert job.retries_left or job.retries_left is None

    def test_a_broken_broker_falls_back_instead_of_raising(self, monkeypatch):
        """Losing durability beats losing the request."""
        monkeypatch.setenv("REDIS_URL", "redis://fake")

        class _Exploding:
            def __getattr__(self, _name):
                raise RuntimeError("broker went away")

        monkeypatch.setattr(queue_mod, "get_redis", lambda: _Exploding())
        bg = _FakeBackgroundTasks()

        assert enqueue(QUEUE_RESOLVE, _record, 5, background_tasks=bg) is False
        assert len(bg.tasks) == 1


class TestLevelRefreshWrapper:
    """The live log-level override (issue #208) reaches a worker process by
    refreshing from the shared store right before each job body runs — at
    _run_with_level_refresh, the one chokepoint every queued job passes
    through, so the override applies app-wide rather than to route
    resolution alone."""

    def test_refreshes_before_running_the_job(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "src.utils.logging.refresh_level_from_store",
            lambda: calls.append("refresh"),
        )

        def _job(x):
            calls.append(("job", x))
            return x * 2

        result = queue_mod._run_with_level_refresh(_job, 21)

        assert result == 42
        assert calls == ["refresh", ("job", 21)]

    @pytest.mark.parametrize("queue_name", [QUEUE_RESOLVE, QUEUE_POSTER, QUEUE_DEFAULT])
    def test_every_queue_wraps_its_job_with_the_refresh(self, broker, queue_name):
        """Not resolve-specific: poster and default (share tiles, stats) jobs
        get the same refresh."""
        enqueue(queue_name, _record, 1)
        q = queue_mod.get_queue(queue_name)
        assert q.jobs[0].func is queue_mod._run_with_level_refresh
        assert q.jobs[0].args == (_record, 1)

    def test_in_process_fallback_does_not_wrap(self, no_broker):
        """The API process already has the override applied in-memory the
        moment it's set — the fallback path must not pay for an extra Redis
        round trip it doesn't need."""
        bg = _FakeBackgroundTasks()
        enqueue(QUEUE_RESOLVE, _record, 1, background_tasks=bg)
        func, _args, _kwargs = bg.tasks[0]
        assert func is _record
