"""The worker's own Redis-connect retry loop (issue #209).

Before this, a worker that couldn't reach Redis within the client's 2s socket
timeout exited(1) immediately. `restart: unless-stopped` relaunched it a few
seconds later, which — when Redis was merely slow rather than actually down —
burned more CPU/memory and deepened the contention that made it slow, turning
one overloaded host into a self-sustaining crash loop. The worker now retries
in place instead of exiting, which is what these tests guard.
"""
from __future__ import annotations

import pytest

import src.jobs.worker as worker_mod


class _FakeSleep:
    """Records requested delays instead of actually waiting."""

    def __init__(self, stop_after: int | None = None):
        self.delays: list[float] = []
        self._stop_after = stop_after

    def __call__(self, seconds: float) -> None:
        self.delays.append(seconds)
        if self._stop_after is not None and len(self.delays) >= self._stop_after:
            raise _StopTest()


class _StopTest(Exception):
    """Escapes an intentionally-infinite retry loop in a test."""


class TestConnectWithRetry:
    def test_returns_immediately_when_redis_is_already_up(self, monkeypatch):
        sentinel = object()
        monkeypatch.setattr(worker_mod, "get_redis", lambda: sentinel)
        sleep = _FakeSleep()

        assert worker_mod._connect_with_retry(sleep=sleep) is sentinel
        assert sleep.delays == []

    def test_retries_with_backoff_until_redis_answers(self, monkeypatch):
        sentinel = object()
        attempts = iter([None, None, sentinel])
        monkeypatch.setattr(worker_mod, "get_redis", lambda: next(attempts))
        reset_calls = []
        monkeypatch.setattr(worker_mod, "reset_redis", lambda: reset_calls.append(1))
        sleep = _FakeSleep()

        assert worker_mod._connect_with_retry(sleep=sleep) is sentinel
        assert sleep.delays == [2, 5]
        assert len(reset_calls) == 2

    def test_backoff_caps_instead_of_growing_unbounded(self, monkeypatch):
        monkeypatch.setattr(worker_mod, "get_redis", lambda: None)
        monkeypatch.setattr(worker_mod, "reset_redis", lambda: None)
        sleep = _FakeSleep(stop_after=8)

        with pytest.raises(_StopTest):
            worker_mod._connect_with_retry(sleep=sleep)

        assert sleep.delays == [2, 5, 10, 30, 60, 60, 60, 60]


class TestMain:
    def test_fails_fast_when_redis_url_is_unset(self, monkeypatch):
        monkeypatch.delenv("REDIS_URL", raising=False)

        def _must_not_be_called():
            raise AssertionError("must not probe Redis when no URL is configured")

        monkeypatch.setattr(worker_mod, "_connect_with_retry", _must_not_be_called)

        assert worker_mod.main([]) == 1

    def test_starts_an_rq_worker_once_connected(self, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "redis://fake")
        sentinel_client = object()
        monkeypatch.setattr(
            worker_mod, "_connect_with_retry", lambda: sentinel_client)

        started = {}

        class _FakeWorker:
            def __init__(self, queues, connection):
                started["queues"] = queues
                started["connection"] = connection

            def work(self, with_scheduler):
                started["with_scheduler"] = with_scheduler

        monkeypatch.setattr("rq.Worker", _FakeWorker)

        assert worker_mod.main(["resolve"]) == 0
        assert started == {
            "queues": ["resolve"],
            "connection": sentinel_client,
            "with_scheduler": False,
        }
