#!/bin/sh
set -e
alembic upgrade head
# --timeout-keep-alive must exceed Caddy's upstream idle timeout (2m by default,
# docs/DEPLOYMENT_VPS.md section 2). uvicorn's default of 5 s makes it the side
# that closes a pooled connection first, and when Caddy reuses that connection at
# the same instant the request fails with a 502 ("EOF" / "connection reset by
# peer" in Caddy's log). GETs are retried transparently by Go's HTTP client;
# POST/PUT/DELETE are not. Issue #400 reproduces it and proves this value.
exec uvicorn api.router:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 300
