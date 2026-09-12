# Keep-alive race reproduction (issue #400)

A self-contained Caddy + uvicorn pair in one container, on loopback, in the
production shape: single uvicorn process, no `--workers`, bare
`reverse_proxy 127.0.0.1:8000`, Caddy's default upstream idle timeout (2 m).
`driver.py` keeps client connections alive and reuses Caddy's pooled upstream
connection at controlled offsets around uvicorn's keep-alive expiry, with and
without the event loop blocked or GIL-starved across that instant.

Not in `tests/` because one full sweep takes ~20 minutes and needs Docker.

```
docker build -t repro400 .
# production shape (uvicorn default --timeout-keep-alive 5)
docker run --rm repro400 -- -- --steps 25 --reps 2 --spread 0.06
# with the entrypoint's value
docker run --rm repro400 -- --timeout-keep-alive 300 -- --scenarios idle-post --steps 2 --reps 30 --spread 0
# with a docker-proxy stand-in between Caddy and uvicorn (loopback-published port)
docker run --rm repro400 --relay -- -- --scenarios idle-post
```

`run.sh [--relay] -- <uvicorn args> -- <driver args>`. Scenarios:

| scenario | what it does |
|---|---|
| `idle` | one pooled connection, reuse it `T ± spread` s later with a GET |
| `idle-post` | same, with a POST carrying a body (not replayable by Go's client) |
| `starved-block` | two pooled connections; `async def` + `time.sleep` blocks the loop across one connection's expiry; reuse the other during the block |
| `starved-cpu` | same, but the blocker is a sync `def` CPU burn in the threadpool (GIL contention, the shape of a geo build) |
| `burst` | six parallel GETs pooled together and all reused `T ± spread` s later |

`+dial` in an outcome means uvicorn logged a new connection during the second
request: Caddy had already dropped the stale one, or Go retried a GET.

## Result that fixed the entrypoint (Caddy v2.11.4, uvicorn 0.52.4)

| configuration | GET outcomes | POST outcomes |
|---|---|---|
| default (5 s), idle, 50 trials each across 4.94–5.06 s | all 200 | **2 × 502**, both at exactly 5.000 s |
| default, 60 trials at exactly 5.000 s | — | **25 × 502** |
| default, docker-proxy relay, idle | all 200 | **1 × 502** at 5.000 s |
| default, loop blocked across expiry, 120 trials each at 0.2 ms steps | all 200 | all 200 |
| default, GIL-starved across expiry, 50 GET / 120 POST trials | all 200 | all 200 |
| default, burst of 6, 300 requests | all 200 | — |
| `--timeout-keep-alive 300`, 60 trials at exactly 5.000 s | all 200 | all 200 |
| `--timeout-keep-alive 300`, reuse at 119.95 / 120 / 120.05 s | — | all 200 (Caddy closed first, fresh dial) |

Caddy's log for the failures, all `"status":502`:
`"msg":"EOF"`, `"read tcp ...: read: connection reset by peer"`,
`"write tcp ...: write: broken pipe"`.

Starvation never produced a 502 and never made GETs fail: Go's `http.Transport`
retries a GET on a reused connection that dies before the first response byte
(`shouldRetryRequest`, and Caddy nils an empty body precisely so that retry can
happen). So `/meta` and `/low-res` — both GETs — cannot get a 502 from this
race; the 502s reported on them in #324/#369 have another cause.
