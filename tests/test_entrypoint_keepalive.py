"""uvicorn's keep-alive timeout must outlive Caddy's upstream idle timeout (#400).

Caddy pools its connections to uvicorn and, by default, keeps an idle one for
2 minutes (``transport http { keepalive }`` in the reverse_proxy docs). uvicorn's
default ``--timeout-keep-alive`` is 5 s, so uvicorn was always the side closing a
pooled connection first, and when Caddy reused that connection at the same
instant the request failed with a 502 — Caddy logs "EOF" or "read: connection
reset by peer". Go's HTTP client retries a GET on a reused connection
transparently, so only POST/PUT/DELETE ever surfaced it, which is why it looked
random. docs/repro/keepalive_502/ reproduces it against a real Caddy + uvicorn
pair; the entrypoint's value is the one that run proved.

The proxy must be the side that closes first: this pins the entrypoint's value
above Caddy's documented default. If Caddy's ``keepalive`` is ever set
explicitly in the Caddyfile, it must stay below this number.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRYPOINT = ROOT / "entrypoint.sh"

CADDY_DEFAULT_UPSTREAM_IDLE_S = 120


def _uvicorn_line() -> str:
    lines = [l for l in ENTRYPOINT.read_text().splitlines() if l.lstrip().startswith("exec uvicorn")]
    assert len(lines) == 1, lines
    return lines[0]


def test_api_entrypoint_sets_keep_alive_above_caddys_idle_timeout():
    m = re.search(r"--timeout-keep-alive[ =](\d+)", _uvicorn_line())
    assert m, "entrypoint.sh no longer passes --timeout-keep-alive; uvicorn's 5 s default races Caddy (#400)"
    assert int(m.group(1)) > CADDY_DEFAULT_UPSTREAM_IDLE_S


def test_api_entrypoint_still_single_process():
    # The payload caches are per-process (see #324); this test is here so that a
    # future --workers change is a deliberate decision, not a side effect.
    assert "--workers" not in _uvicorn_line()
