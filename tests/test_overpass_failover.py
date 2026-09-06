"""Tests for _overpass transport: how it paces, waits and fails over.

Regression cover for the 2026-09-06 incident. Overpass-api.de was healthy the
whole time — it answered a full 5.2 MB strategy-C query in 8.4s with both slots
free — but every rail resolve came back degraded after 213-316s, against a
client that gives up at 120s. The transport treated a 429 ("busy, come back in
a moment") exactly like a dead host and immediately failed over to two mirrors
that cost the full 45s socket timeout each, roughly 90s per query. It then
reported only the *last* error, so the logs named a mirror and never revealed
that the primary had been reached at all.
"""

from contextlib import contextmanager

import pytest

from src.services import overpass_service as ov
from src.services.overpass_service import OverpassError, _overpass

_PRIMARY = ov._OVERPASS_ENDPOINTS[0]
_FALLBACK = ov._OVERPASS_ENDPOINTS[-1]
_QUERY = "[out:json];node(1);out;"


class _Resp:
    """Minimal stand-in for requests.Response."""

    def __init__(self, status=200, payload=None, text="", headers=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload
        self.text = text
        self.content = (text or "").encode()

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


@pytest.fixture
def transport(monkeypatch):
    """Record every POST and every sleep; drive responses from a script.

    Both are the measurements under test: which hosts we talked to, and how
    long we were willing to wait rather than talk to a different one.
    """
    calls: list[str] = []
    sleeps: list[float] = []
    script: dict[str, list] = {}

    def _post(url, **_kwargs):
        calls.append(url)
        queued = script.get(url)
        if not queued:
            raise AssertionError(f"unscripted call to {url}")
        outcome = queued.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(ov.requests, "post", _post)
    monkeypatch.setattr("time.sleep", lambda s: sleeps.append(s))
    # No broker in the test suite, so the limiter is already a no-op; pin it so
    # a developer machine with REDIS_URL set doesn't change what these assert.
    monkeypatch.setattr(ov, "get_redis", lambda: None, raising=False)
    monkeypatch.setattr("src.jobs.upstream_slots.get_redis", lambda: None)

    return type("T", (), {
        "calls": calls, "sleeps": sleeps, "script": script,
    })()


class TestBusyHostIsWaitedOutNotAbandoned:
    """The core behaviour change. A 429 is a healthy host asking for a moment."""

    def test_waits_and_retries_the_same_host(self, transport):
        transport.script[_PRIMARY] = [
            _Resp(429, text="Slot available after: ..., in 3 seconds."),
            _Resp(200, payload={"elements": [1]}),
        ]

        assert _overpass(_QUERY) == {"elements": [1]}
        assert transport.calls == [_PRIMARY, _PRIMARY]
        assert transport.sleeps == [3.0]

    def test_never_touches_the_fallback_while_the_primary_is_merely_busy(
        self, transport,
    ):
        """The incident in one assertion: a busy primary must not send us to a
        mirror that takes 36.9s for a trivial query."""
        transport.script[_PRIMARY] = [
            _Resp(429, text="in 2 seconds"),
            _Resp(200, payload={"elements": []}),
        ]
        transport.script[_FALLBACK] = [AssertionError("must not fail over on 429")]

        _overpass(_QUERY)
        assert _FALLBACK not in transport.calls

    def test_gives_up_on_a_host_that_stays_busy(self, transport):
        """Bounded patience: after _SLOT_RETRIES waits we do move on."""
        busy = [_Resp(429, text="in 1 seconds") for _ in range(1 + ov._SLOT_RETRIES)]
        transport.script[_PRIMARY] = busy
        transport.script[_FALLBACK] = [_Resp(200, payload={"elements": ["fb"]})]

        assert _overpass(_QUERY) == {"elements": ["fb"]}
        assert transport.calls.count(_PRIMARY) == 1 + ov._SLOT_RETRIES
        assert transport.sleeps == [1.0, 1.0]

    def test_does_not_wait_longer_than_the_cap(self, transport):
        """A slot an hour away is not worth holding a resolve open for."""
        transport.script[_PRIMARY] = [_Resp(429, text="in 3600 seconds")]
        transport.script[_FALLBACK] = [_Resp(200, payload={"elements": []})]

        _overpass(_QUERY)
        assert transport.sleeps == []
        assert _FALLBACK in transport.calls

    def test_total_waiting_is_bounded_across_hosts(self, transport):
        """Per-host patience alone would let a query 429'd everywhere sleep for
        minutes — trading the old pathology for a new one."""
        busy = _Resp(429, text=f"in {ov._MAX_SLOT_WAIT_S:d} seconds")
        for url in ov._OVERPASS_ENDPOINTS:
            transport.script[url] = [busy] * (1 + ov._SLOT_RETRIES)

        with pytest.raises(OverpassError):
            _overpass(_QUERY)

        assert sum(transport.sleeps) <= ov._MAX_TOTAL_WAIT_S


class TestRetryAfterParsing:
    def test_prefers_the_standard_header(self, transport):
        transport.script[_PRIMARY] = [
            _Resp(429, headers={"Retry-After": "7"}, text="in 99 seconds"),
            _Resp(200, payload={}),
        ]
        _overpass(_QUERY)
        assert transport.sleeps == [7.0]

    def test_falls_back_to_a_short_default_when_unstated(self, transport):
        transport.script[_PRIMARY] = [_Resp(429, text="too many requests"),
                                      _Resp(200, payload={})]
        _overpass(_QUERY)
        assert transport.sleeps == [ov._DEFAULT_SLOT_WAIT_S]

    def test_caps_an_over_long_header(self, transport):
        transport.script[_PRIMARY] = [_Resp(429, headers={"Retry-After": "5000"})]
        transport.script[_FALLBACK] = [_Resp(200, payload={})]
        _overpass(_QUERY)
        assert transport.sleeps == []


class TestBrokenHostsFailOverImmediately:
    """The other half: where moving on really is the faster path."""

    def test_connection_error_moves_on_without_waiting(self, transport):
        transport.script[_PRIMARY] = [OSError("connection refused")]
        transport.script[_FALLBACK] = [_Resp(200, payload={"elements": ["fb"]})]

        assert _overpass(_QUERY) == {"elements": ["fb"]}
        assert transport.sleeps == [], "a broken host must not be waited on"

    @pytest.mark.parametrize("status", sorted(ov._OVERPASS_RETRYABLE))
    def test_server_errors_move_on(self, transport, status):
        transport.script[_PRIMARY] = [_Resp(status)]
        transport.script[_FALLBACK] = [_Resp(200, payload={"elements": []})]

        _overpass(_QUERY)
        assert transport.calls == [_PRIMARY, _FALLBACK]

    def test_unparseable_body_moves_on(self, transport):
        """A 200 carrying an Overpass runtime-error page, which the QL
        [timeout:30] directive can produce well inside our socket timeout."""
        transport.script[_PRIMARY] = [_Resp(200, payload=None, text="<html>error")]
        transport.script[_FALLBACK] = [_Resp(200, payload={"elements": []})]

        _overpass(_QUERY)
        assert transport.calls == [_PRIMARY, _FALLBACK]

    def test_429_is_not_classed_as_a_broken_host(self):
        """Guards the semantic change directly: putting 429 back in here would
        silently restore the stampede the tests above forbid."""
        assert ov._RATE_LIMITED not in ov._OVERPASS_RETRYABLE


class TestFailureReporting:
    def test_error_names_every_endpoint_attempted(self, transport):
        """Phase 1 of the fix. The old message kept only the last error, so it
        named one mirror while claiming "all endpoints" — which is why the
        incident logs never showed what the primary actually returned."""
        transport.script[_PRIMARY] = [_Resp(429, text="in 1 seconds")] * (
            1 + ov._SLOT_RETRIES)
        transport.script[_FALLBACK] = [TimeoutError("read timed out")]

        with pytest.raises(OverpassError) as err:
            _overpass(_QUERY)

        message = str(err.value)
        assert _PRIMARY in message and _FALLBACK in message
        assert "429" in message and "TimeoutError" in message

    def test_the_incident_cascade_is_reported_in_full(self, transport):
        """Every endpoint read-timing-out — the shape seen on 2026-09-06."""
        transport.script[_PRIMARY] = [TimeoutError("read timed out")]
        transport.script[_FALLBACK] = [TimeoutError("read timed out")]

        with pytest.raises(OverpassError) as err:
            _overpass(_QUERY)

        assert str(err.value).count("TimeoutError") == 2
        assert transport.sleeps == []


class TestPacing:
    def test_no_free_slot_moves_to_the_next_host(self, monkeypatch, transport):
        """When our own traffic is saturating a host, another endpoint has its
        own quota — queueing behind ourselves does not."""
        @contextmanager
        def _denied(name, _limit, **_kw):
            yield name != ov._slot_name(_PRIMARY)

        monkeypatch.setattr(ov, "slot", _denied)
        transport.script[_FALLBACK] = [_Resp(200, payload={"elements": []})]

        _overpass(_QUERY)
        assert transport.calls == [_FALLBACK]

    def test_dead_mirror_is_not_in_the_rotation(self):
        """kumi.systems answered nothing within 50s from the production VPS, so
        every query that reached it paid the full socket timeout to find out."""
        assert not any("kumi" in url for url in ov._OVERPASS_ENDPOINTS)


class TestResponseCaching:
    """The demand-reduction half. A retry — by hand, or by the hourly degraded
    sweep — re-asks a byte-identical question, and before this every one of them
    went to the network. That repetition is what escalated a soft rate limit into
    an outright IPv4 block on 2026-09-06.
    """

    @pytest.fixture
    def cached(self, monkeypatch):
        import fakeredis

        from src.jobs import upstream_cache
        client = fakeredis.FakeRedis()
        monkeypatch.setattr(upstream_cache, "get_redis", lambda: client)
        return client

    def test_an_identical_query_is_not_re_requested(self, transport, cached):
        transport.script[_PRIMARY] = [_Resp(200, payload={"elements": [1]},
                                           text='{"elements": [1]}')]

        first = _overpass(_QUERY)
        second = _overpass(_QUERY)

        assert first == second == {"elements": [1]}
        assert transport.calls == [_PRIMARY], "the second call must be served from cache"

    def test_a_cache_hit_costs_no_slot_and_no_wait(self, transport, cached,
                                                   monkeypatch):
        """A hit must short-circuit before pacing: queueing behind our own
        concurrency limit to answer from memory would be absurd."""
        transport.script[_PRIMARY] = [_Resp(200, payload={"elements": []},
                                           text='{"elements": []}')]
        _overpass(_QUERY)

        def _must_not_acquire(*_a, **_kw):
            raise AssertionError("a cache hit must not take a slot")

        monkeypatch.setattr(ov, "slot", _must_not_acquire)
        assert _overpass(_QUERY) == {"elements": []}

    def test_a_different_query_still_goes_to_the_network(self, transport, cached):
        transport.script[_PRIMARY] = [
            _Resp(200, payload={"elements": ["a"]}, text='{"elements": ["a"]}'),
            _Resp(200, payload={"elements": ["b"]}, text='{"elements": ["b"]}'),
        ]

        assert _overpass("query one") == {"elements": ["a"]}
        assert _overpass("query two") == {"elements": ["b"]}
        assert transport.calls == [_PRIMARY, _PRIMARY]

    def test_failures_are_not_cached(self, transport, cached):
        """Only a parsed success is stored. Caching a 429 or a timeout would
        turn a transient upstream problem into a day-long one."""
        transport.script[_PRIMARY] = [_Resp(504), _Resp(504)]
        transport.script[_FALLBACK] = [TimeoutError("nope"), TimeoutError("nope")]

        for _ in range(2):
            with pytest.raises(OverpassError):
                _overpass(_QUERY)
        assert transport.calls.count(_PRIMARY) == 2, "a failure must be retried, not cached"


class TestPolitenessBound:
    def test_only_one_overpass_request_at_a_time(self):
        """Matching the advertised cap of 2 exactly left no margin and 429'd
        constantly — and a rejection costs 10-14s, because the dispatcher queues
        you before refusing. One is deliberate, not a typo."""
        assert ov._OVERPASS_CONCURRENCY == 1
