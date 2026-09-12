#!/bin/sh
# usage: run.sh [--relay] -- <uvicorn extra args> -- <driver args>
RELAY=0
if [ "$1" = "--relay" ]; then RELAY=1; shift; fi
[ "$1" = "--" ] && shift
UV_ARGS=""
while [ $# -gt 0 ] && [ "$1" != "--" ]; do UV_ARGS="$UV_ARGS $1"; shift; done
[ "$1" = "--" ] && shift
caddy run --config /r/Caddyfile --adapter caddyfile >/tmp/caddy.stdout 2>&1 &
if [ $RELAY = 1 ]; then
  python /r/relay.py &
  uvicorn app:app --host 127.0.0.1 --port 8001 --log-level trace $UV_ARGS >/tmp/uvicorn.log 2>&1 &
else
  uvicorn app:app --host 127.0.0.1 --port 8000 --log-level trace $UV_ARGS >/tmp/uvicorn.log 2>&1 &
fi
sleep 1.5
echo "== uvicorn args:$UV_ARGS relay=$RELAY caddy=$(caddy version | cut -d' ' -f1)"
python /r/driver.py "$@"
echo "== caddy error-level log lines: $(grep -c '"level":"error"' /tmp/caddy.log)"
grep '"level":"error"' /tmp/caddy.log | head -5 | cut -c1-700
