# Observability: Loki + Prometheus + Grafana (issue #205)

Colocated on the NAS — generous disk, no CPU contention with the VPS's
production traffic. See `docs/DEPLOYMENT_VPS.md`'s "Observability" section
for the VPS-side half (the Tailscale tunnel + the Alloy shipper that pushes
here) and `docs/LOGGING.md` for the logging conventions the log lines below
follow.

## Why Loki + Prometheus, not Mimir

Grafana natively takes both Prometheus and Loki as datasources side by side
— that gets "everything in one Grafana" without introducing Mimir, which is
built for horizontal, multi-tenant scale that doesn't apply here (one app, a
handful of concurrent users). Plain Prometheus, with
`--web.enable-remote-write-receiver` so Alloy can push to it instead of
Prometheus reaching back out to scrape the VPS, is simpler and needs no
extra storage/ring component for zero benefit at this size. Revisit only if
this genuinely needs to scale multi-tenant later — repointing Alloy's
`remote_write` endpoint at Mimir afterwards is cheap; standing up Mimir now
for that hypothetical isn't.

## NAS-side compose (sketch — adapt, don't copy-paste as final)

Not committed to this repo as a working file — like the VPS's real
`docker-compose.yml`, this is host-specific (paths, the NAS's own Docker
setup). Sketch, matching the pattern `docker-compose.yml.example` already
sets for the VPS side:

```yaml
services:
  loki:
    image: grafana/loki:latest
    container_name: observability-loki
    restart: unless-stopped
    ports:
      - "3100:3100"   # reachable over Tailscale only in practice — nothing
                       # forwards this from the NAS's router to the WAN
    volumes:
      - ./loki/config.yaml:/etc/loki/config.yaml:ro
      - ./loki/data:/loki
    command: ["-config.file=/etc/loki/config.yaml"]

  prometheus:
    image: prom/prometheus:latest
    container_name: observability-prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/data:/prometheus
    command:
      - "--config.file=/etc/prometheus/prometheus.yml"
      - "--storage.tsdb.path=/prometheus"
      - "--web.enable-remote-write-receiver"   # Alloy pushes here

  grafana:
    image: grafana/grafana:latest
    container_name: observability-grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - ./grafana/data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
```

If the NAS's Docker setup lets you bind these to the Tailscale interface
specifically rather than `0.0.0.0`, do that. Otherwise this relies on the
NAS's router/firewall not forwarding these ports to the WAN — the same
"Docker writes NAT rules that can bypass a host firewall" gotcha
`docs/DEPLOYMENT_VPS.md` §1 documents for the VPS applies here too if the
NAS's router does UPnP/port-forwarding. Verify from outside the LAN before
trusting it.

**Not verified against live Loki/Prometheus/Grafana binaries from the
session that wrote this** — same caveat as the VPS-side Alloy config:
documented starting point, not tested software.

## Loki retention

Cap it explicitly — "the NAS has disk to spare" is not the same as
"unbounded is fine." A starting point matching the existing 30-day backup
convention (`src/backup/backup_service.py`), in `loki/config.yaml`:

```yaml
limits_config:
  retention_period: 720h   # 30 days

compactor:
  working_directory: /loki/compactor
  retention_enabled: true
  delete_request_store: filesystem
```

Monolithic mode, filesystem storage — no object store (S3/MinIO) needed at
this scale; add the `schema_config`/`storage_config` blocks Loki's own
"getting started" docs specify for filesystem storage alongside this.

## Grafana datasources

Both point at `localhost` since everything is colocated —
`grafana/provisioning/datasources/datasources.yaml`:

```yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    access: proxy
    url: http://prometheus:9090
    isDefault: true
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
```

## Queries an operator actually runs

Log lines look like:

```
2026-08-10 18:06:58,123 - api.polarsteps - WARNING - request_id=a1b2c3d4 user_id=42 - polarsteps connect failed user_id=42
```

`request_id=` and `user_id=` are real logfmt tokens — `| logfmt` extracts
them as labels for the query. `%(levelname)s` (`WARNING` above) is
**positional, not a `level=` key** (see `docs/LOGGING.md`), so level
filtering is a substring match, not a logfmt field.

- **One request end to end** — the original "reconstruct what happened,
  without asking the user" ask, scoped to a single request:
  ```logql
  {service="viewtripweb"} | logfmt | request_id="a1b2c3d4"
  ```
- **One user's whole session across concurrent traffic** — the broader
  version of the same ask, across every request that user made in a time
  window:
  ```logql
  {service="viewtripweb"} | logfmt | user_id="42"
  ```
- **Error rate** (substring match — see the level-field note above):
  ```logql
  sum(rate({service="viewtripweb"} |= "ERROR" [5m]))
  ```
- **A specific external integration's failures** (matches
  `track_external()`'s log format, `src/utils/metrics.py`):
  ```logql
  {service="viewtripweb"} |= "external call failed" |= "service=polarsteps"
  ```

## Alerting (replaces the earlier idea of adding Sentry)

Self-hosted, no third-party data egress — a better fit for a product built
around zero-knowledge E2EE than shipping stack traces to an external
service (`docs/ENCRYPTION.md`). Two starting rules in Grafana Alerting:

1. **Error-rate spike** — the LogQL query above, alert if `> N` errors over
   5 minutes for some threshold `N` worth calibrating against real traffic
   first (start loose, tighten once you know the baseline).
2. **Scheduled job failure** — `viewtrip_job_runs_total{result="error"}`
   (Prometheus, already emitted by `src/utils/metrics.py`'s
   `record_job_event`) — alert on any increment, since a failed daily
   backup or WAL checkpoint is always worth knowing about immediately, not
   discovering days later.

## Dozzle

Already deployed (`/opt/dozzle` on the VPS, port 8892) and keeps covering
live-tail — not part of this stack, and this doesn't replace it. Loki adds
"filter by user/request after the fact, across concurrent traffic, after a
deploy has recycled the container" — which Dozzle was never meant to do.
Worth a one-time check that it isn't reachable without auth on a
publicly-routed port (Dozzle has none built in).
