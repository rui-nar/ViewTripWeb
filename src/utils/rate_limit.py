"""Keyed, non-blocking sliding-window rate limiter (issue #110).

Used for the actions that cause the server to send mail on a user's behalf —
invite emails and verification resends — where an unbounded caller turns the
app into an open relay against its own provider reputation.

**Why not reuse ``src/api/strava_client.RateLimiter``** (#130): that one blocks
for up to 60s waiting for a slot and raises a Strava-worded error, and it holds
a single global window rather than one per key. Blocking is right for an
upstream quota, where the work must eventually happen; it is wrong here, where
the honest answer to "you have sent too many invites" is an immediate 429, not
a parked request thread. The two limiters are deliberately separate.

**Per-process, like #130's.** ``entrypoint.sh`` runs a single worker, so one
process sees every request. A second worker would get its own counters and
the effective limit would multiply by the worker count; going wider means
moving this state to the database or Redis.
"""
from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from typing import Callable, Deque, Dict


class KeyedRateLimiter:
    """Allows *max_events* per *window_seconds* for each key independently."""

    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._max_events = max_events
        self._window = window_seconds
        self._clock = clock
        self._events: Dict[str, Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def try_acquire(self, key: str) -> bool:
        """Record an event against *key*. False if that would exceed the limit.

        Never blocks and never raises — the caller decides what a refusal means
        (almost always a 429).
        """
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            if len(events) >= self._max_events:
                return False
            events.append(now)
            return True

    def remaining(self, key: str) -> int:
        """Events still allowed for *key* in the current window."""
        now = self._clock()
        cutoff = now - self._window
        with self._lock:
            events = self._events[key]
            while events and events[0] < cutoff:
                events.popleft()
            return self._max_events - len(events)

    def reset(self) -> None:
        """Forget every key. For tests — instances are module-level, so without
        this one test's calls count against the next."""
        with self._lock:
            self._events.clear()


# Ten mail-sending actions per user per hour. High enough that a person adding
# their travel companions one at a time never notices; low enough that a
# compromised account cannot mail thousands of strangers from our domain.
_MAIL_ACTIONS_PER_HOUR = 10

_mail_limiter = KeyedRateLimiter(_MAIL_ACTIONS_PER_HOUR, 3600.0)


def consume_rate_limit(key: str) -> bool:
    """Claim one mail-sending action for *key*. False when the caller is over
    the limit."""
    return _mail_limiter.try_acquire(key)


def reset_rate_limits() -> None:
    """Clear the shared mail limiter. For tests."""
    _mail_limiter.reset()
