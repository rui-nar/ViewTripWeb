# Logging

Conventions for adding or reviewing `logger.*()` calls anywhere in `api/` or
`src/`. This is the practical reference — if you're touching a route or
service file and need to know what level to use, how to format a message, or
what never gets logged, this page has it. For the *why* (issue #205's audit,
the infrastructure plan, open decisions) see
`docs/LOGGING_OBSERVABILITY_PLAN.md`; if the two ever disagree, the plan doc
is the source of truth and both should be updated together.

## Getting a logger

Always:

```python
from src.utils.logging import get_logger

_log = get_logger(__name__)
```

Never bare `logging.getLogger(__name__)`. Three files still do this
(`api/poster.py`, `src/email/service.py`, `src/tile_renderer.py`) — fix it if
you touch one of them, but don't go looking for others outside your change.

## Levels

| Level | Use for |
|---|---|
| `DEBUG` | Verbose internals; the access-log line for chatty/polled routes (see the allowlist below). |
| `INFO` | Normal lifecycle: a sync/import completed with counts, a job ran, a request completed (non-chatty route), an external call succeeded. |
| `WARNING` | Degraded-but-handled: retried, fell back, partial-batch failure, cache forced a refetch. |
| `ERROR` (via `.exception()`) | Something failed and the user got a worse outcome than they should have. |

For `ERROR`, always call `.exception()`, not `.error()`, inside an `except`
block — `.exception()` captures the traceback, `.error()` doesn't. This is
the single most common mistake to watch for in review.

## Format

`configure_logging()`'s formatter is logfmt-shaped, not free text: a logfmt
preamble (`request_id=... user_id=...`, populated by a `logging.Filter`)
followed by the human-readable message.

Why `request_id`/`user_id` live in the message body instead of becoming Loki
labels: Loki indexes labels, not message content, and a label whose values
come from user/request identity has unbounded cardinality — one Loki time
series per user or per request would eventually take Loki down with it (same
reasoning as `docs/METRICS.md`'s "no label may carry user data" rule for
Prometheus). So they're parsed out of the message body at query time instead,
via `| logfmt` in a LogQL query. Keep messages human-grep-able too — this
isn't JSON, it's logfmt.

> **Status:** the `request_id`/`user_id` contextvars, the `logging.Filter`
> that injects them, and the final formatter string are being built
> concurrently (issue #205, Unit 0.2, touching `src/utils/logging.py` and
> `api/router.py`). The names above are what the plan specifies. If that work
> has landed by the time you read this, spot-check this section against the
> actual field names and format string in `src/utils/logging.py` — don't
> assume this doc is still accurate on that specific detail.

## Redaction

Never log:

- JWTs
- passwords
- Stripe secret keys / other API secrets
- E2EE key material
- raw request bodies

Email logging: log the recipient and subject only, never the body. Exception:
the `ConsoleEmailService` dev backend logging the full body is fine — that's
a dev-only code path, not something that reaches a shared log stream.

## External calls: `track_external()`

`src/utils/metrics.py:track_external()` is the single choke point for
logging (and metrics) around any outbound call to a third-party service. It
already wraps Strava, Polarsteps, Google Translate and SMTP for Prometheus
metrics, and is being upgraded to log too (`INFO` on success, `WARNING` on
failure) as part of issue #205.

If you're adding a new external HTTP call, wrap it in `track_external`
instead of hand-rolling your own try/except + log pattern:

```python
from src.utils.metrics import track_external

with track_external("polarsteps", "/v1/trips/{id}") as call:
    response = httpx.get(url)
    if response.status_code >= 400:
        call.outcome = outcome_for_status(response.status_code)
    response.raise_for_status()
```

Don't add a second, parallel logging pattern for external calls — if
`track_external` doesn't fit a case, that's worth raising rather than working
around.

## Chatty routes: DEBUG allowlist

Read-only, polled-or-per-paint routes log their access-log line at `DEBUG`
instead of `INFO`, so normal browsing doesn't drown out the signal:

- poster/job-status polling
- tile serving
- `GET /api/geo/project` (and its low-res variant)
- `GET /api/version`
- `/metrics`

Everything else — writes, auth, sync/import, external calls — logs at
`INFO`. This is a hardcoded path-template allowlist checked in **one place**,
the access-log middleware, not a per-route decorator. If you're adding a new
chatty/polled read-only route, add it to that allowlist rather than
suppressing its own logging locally.

## Testing

Every logging change needs a `caplog`-based test proving the *specific* log
line fires at the right level — not just that behavior is unchanged around
it. Add the test to the existing test file for that module if one exists;
otherwise create `tests/test_<module>_logging.py`.

```python
def test_malformed_activity_logs_warning(caplog):
    with caplog.at_level(logging.WARNING):
        parse_activities_or_log([bad_activity], source="strava")
    assert "dropped" in caplog.text
    assert "strava" in caplog.text
```

## See also

- `docs/LOGGING_OBSERVABILITY_PLAN.md` — the full plan: audit of where
  logging is missing, infrastructure (Loki/Grafana/Alloy) decisions, open
  questions.
- `docs/METRICS.md` — Prometheus metrics; same cardinality discipline
  (`normalise_path`, closed label sets) that motivates keeping
  `request_id`/`user_id` out of Loki labels here.
