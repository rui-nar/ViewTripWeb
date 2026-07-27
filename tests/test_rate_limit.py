"""KeyedRateLimiter (issue #110).

Driven by an injected clock rather than real time — a window test that sleeps
is slow and flaky, and this way the boundary can be probed exactly.
"""
from __future__ import annotations

from src.utils.rate_limit import KeyedRateLimiter


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class TestWindow:
    def test_allows_up_to_the_limit(self):
        limiter = KeyedRateLimiter(3, 60.0, clock=_Clock())
        assert [limiter.try_acquire("u1") for _ in range(3)] == [True] * 3

    def test_refuses_past_the_limit(self):
        limiter = KeyedRateLimiter(3, 60.0, clock=_Clock())
        for _ in range(3):
            limiter.try_acquire("u1")
        assert limiter.try_acquire("u1") is False

    def test_window_slides_rather_than_resetting(self):
        """A fixed-bucket limiter would let 2N through across a boundary."""
        clock = _Clock()
        limiter = KeyedRateLimiter(2, 60.0, clock=clock)
        limiter.try_acquire("u1")          # t=0
        clock.advance(30)
        limiter.try_acquire("u1")          # t=30
        assert limiter.try_acquire("u1") is False

        clock.advance(31)                  # t=61 — the t=0 event has aged out
        assert limiter.try_acquire("u1") is True
        # ...but the t=30 event has not, so the next is still refused.
        assert limiter.try_acquire("u1") is False

    def test_recovers_after_full_window(self):
        clock = _Clock()
        limiter = KeyedRateLimiter(2, 60.0, clock=clock)
        limiter.try_acquire("u1")
        limiter.try_acquire("u1")
        clock.advance(61)
        assert limiter.try_acquire("u1") is True


class TestKeysAreIndependent:
    def test_one_key_exhausted_does_not_affect_another(self):
        limiter = KeyedRateLimiter(1, 60.0, clock=_Clock())
        assert limiter.try_acquire("u1") is True
        assert limiter.try_acquire("u1") is False
        assert limiter.try_acquire("u2") is True

    def test_remaining_is_per_key(self):
        limiter = KeyedRateLimiter(3, 60.0, clock=_Clock())
        limiter.try_acquire("u1")
        assert limiter.remaining("u1") == 2
        assert limiter.remaining("u2") == 3


class TestReset:
    def test_reset_clears_every_key(self):
        limiter = KeyedRateLimiter(1, 60.0, clock=_Clock())
        limiter.try_acquire("u1")
        limiter.try_acquire("u2")
        limiter.reset()
        assert limiter.try_acquire("u1") is True
        assert limiter.try_acquire("u2") is True


class TestRefusalDoesNotConsume:
    def test_refused_attempts_do_not_extend_the_window(self):
        """A refused attempt must not be recorded, or hammering the endpoint
        would keep pushing the recovery time outwards forever."""
        clock = _Clock()
        limiter = KeyedRateLimiter(1, 60.0, clock=clock)
        assert limiter.try_acquire("u1") is True

        clock.advance(30)
        for _ in range(5):
            assert limiter.try_acquire("u1") is False

        clock.advance(31)  # 61s after the one accepted event
        assert limiter.try_acquire("u1") is True
