# VPS Deployment (traxjourney.com)

Runbook for the production deployment on an OVH VPS, replacing the Synology
NAS as the public-facing host. The NAS deployment (`deploy.ps1`,
`viewtrip.narciso.synology.me`) is unaffected and kept running as a fallback
during the transition — this is a separate host on a separate domain, not a
cutover of existing traffic.

## Infrastructure

| Item | Value |
|------|-------|
| Domain | traxjourney.com (+ www, redirected to apex) |
| Provider | OVH, VPS-1 2027 range |
| Specs | 2 vCore, 4 GB RAM, 40 GB NVMe SSD, Strasbourg (FR) datacenter |
| Image | Debian 12 - Docker (Docker preinstalled) |
| SSH user | `debian` (OVH default account, sudo + docker group) |
| App directory | `/opt/viewtrip/` (`db/`, `config/`, `data/`, `docker-compose.yml`, `.env`) |
| Reverse proxy | Caddy (automatic Let's Encrypt TLS) |

## 1. VPS hardening

- SSH key auth only: generated a dedicated key locally
  (`~/.ssh/traxjourney_vps`), copied to `~/.ssh/authorized_keys` for the
  `debian` user, then in `/etc/ssh/sshd_config`:
  - `PermitRootLogin no` (already default on the OVH image)
  - `PasswordAuthentication no`
  - `systemctl restart sshd` — **always verify the key login works from a
    fresh terminal before this step**, to avoid a lockout.
- Firewall: `ufw` (not raw `iptables` — Debian doesn't ship ufw by default,
  `apt install ufw` first). Rules: allow OpenSSH, 80/tcp, 443/tcp, then
  `ufw enable`.
- GHCR auth: logged in with a **read-only** PAT (`read:packages` scope only),
  not the push token used by `deploy.ps1` locally — limits blast radius if
  the VPS is ever compromised.

**Gotcha:** Docker manipulates `iptables` directly when a container port is
published (`ports:` in compose), and can bypass ufw's rules entirely. Fix:
bind published ports to loopback only, e.g. `"127.0.0.1:8000:8000"`, so the
port is reachable from Caddy on the same host but never exposed publicly
regardless of firewall state.

## 2. Caddy reverse proxy

Installed from Caddy's official apt repo. `/etc/caddy/Caddyfile`:

```
traxjourney.com {
    reverse_proxy 127.0.0.1:8000
}

www.traxjourney.com {
    redir https://traxjourney.com{uri} permanent
}
```

**Gotcha:** the Caddy Debian package ships a default `:80 { root * ...;
file_server }` block in the Caddyfile. This block has no hostname, so it
matches *any* host on port 80 and will intercept requests meant for your
domain block — delete it, don't just append your own block alongside it.

`systemctl reload caddy` after any edit. Cert issuance is automatic on first
request, provided DNS already resolves and 80/443 are open.

## 3. App deployment

`/opt/viewtrip/docker-compose.yml` mirrors the NAS prod compose
(`/volume2/docker/viewtrip/docker-compose.yml`), with three differences:

- Port bound to loopback (`127.0.0.1:8000:8000`) instead of `7777:8000`.
- `FRONTEND_ORIGIN` / `STRAVA_REDIRECT_URI` point at `traxjourney.com`.
- `JWT_SECRET` freshly generated (`openssl rand -hex 32`) — not reused from
  the NAS, no reason to carry an old session-signing key to a new host.

All other env values (Mapbox, Google client ID/Translate key, Strava
client ID/secret) are unchanged from NAS prod.

**Before going live:** add `https://traxjourney.com/...` equivalents to
Google OAuth console's authorized redirect URIs and Strava's app
"Authorization Callback Domain" — both are still only registered for the
`narciso.synology.me` domain, and login/Strava sync will fail on the new
domain until updated.

### Background job worker (optional, issue #173)

The API serves fine on its own: with `REDIS_URL` unset, every background job
(route resolution, poster rendering, share tiles, stats) runs inside the API
process via FastAPI `BackgroundTasks`. That is the original behaviour and a
reasonable setup for this instance's load.

Adding the `redis` + worker services buys two things:

- **Durability.** A job survives an API restart. Previously a restart mid-resolve
  left a segment on `route_status="pending"` forever, and the only recovery was
  client-side — it ran when someone happened to reopen the project.
- **A real concurrency bound.** An RQ worker runs one job at a time, so the
  number of processes listening on a queue *is* that queue's parallelism.

The bounds are not the same for every queue, which is why there are two worker
services rather than one scaled to two replicas (issue #188): `resolve` is
capped at 2 because Overpass rate-limits per IP and it is a free public service,
while `poster` is capped at **1** because two concurrent A0 renders are what
takes a small host out on memory. Identical replicas can only give every queue
the same bound, so they cannot express this.

`QUEUE_MAX_CONCURRENCY` in `src/jobs/queue.py` is the source of truth for those
numbers, and `tests/test_worker_topology.py` fails if the compose example stops
matching it. Change the map and the compose file together.

See `docker-compose.yml.example` for the service definitions. Three things about
it are easy to get wrong:

- The workers **must mount the same host paths** as the API container. The
  database is a SQLite file, so "sharing" it means sharing the volume, on one
  host. Two engines writing one file is fine — WAL and a 30 s `busy_timeout` are
  set on every connection (`models/db.py`) — but only on the same machine.
- Redis needs `--appendonly yes`. Without it, a broker restart silently drops
  every queued job, which is the exact failure the queue was added to fix.
- Do **not** publish Redis' port. Docker publishes ports by writing DNAT rules
  that bypass `ufw`, so "the firewall blocks it" is not true of a published
  port — and an unauthenticated Redis reachable from the internet is a
  well-known way to lose a host.

The workers set `VIEWTRIP_ROLE=worker`, which stops them running migrations, the
admin seed, and the scheduled jobs. Only the API container owns those: two
containers racing `alembic upgrade head` at boot, or each taking its own nightly
backup and 60 s WAL checkpoint, is the failure that guards against.

Keep both worker services on the **same image tag** as the API. They share one
image and only the API runs migrations, so a worker left on an older tag would
run stale job code against a schema it does not know about.

`deploy.ps1` needs no changes for any of this: it builds/pushes the image and
then runs `docker compose down && pull && up -d`, which is service-agnostic.
Adding the services to each host's compose file and the keys to its `.env` is
the whole deployment change.

**Rollback** is unsetting `REDIS_URL` and removing the worker services. No image
rebuild — jobs simply run in-process again.

If you scrape `/metrics`, also set `PROMETHEUS_MULTIPROC_DIR` to a directory
both containers mount. Without it the scrape only sees the API process and
job-side DB metrics silently go missing (see docs/METRICS.md).

## 4. Data migration (NAS -> VPS)

1. **Consistent DB snapshot on the NAS**, via SQLite's online backup API in a
   throwaway container (safe on a live DB — unlike a raw `cp`, correctly
   handles WAL mode, which the app already runs — see `models/db.py`):
   ```bash
   ssh -p 4488 Rui@narciso.synology.me "DOCKER=\$(command -v docker 2>/dev/null || ls /var/packages/ContainerManager/target/usr/bin/docker /var/packages/Docker/target/usr/bin/docker /usr/local/bin/docker 2>/dev/null | head -1); \$DOCKER run --rm -v /volume2/docker/viewtrip/db:/db python:3.11-slim python3 -c \"import sqlite3; s=sqlite3.connect('/db/viewtripweb.db'); d=sqlite3.connect('/db/migration_backup.db'); s.backup(d); d.close(); s.close(); print('backup done')\""
   ```
   **Gotcha:** `docker` isn't in `PATH` for non-interactive SSH sessions on
   Synology — same issue `deploy.ps1`'s remote script already works around;
   resolve the binary path explicitly as above.

2. **Stop the VPS container first** if anything is already running there —
   overwriting a SQLite file out from under a live connection risks
   corruption: `cd /opt/viewtrip && docker compose down`.

3. **Copy DB + data + config from NAS straight to the VPS** (no need to hop
   through a local machine — the VPS has direct SSH reach to the NAS):
   ```bash
   scp -O -P 4488 Rui@narciso.synology.me:/volume2/docker/viewtrip/db/migration_backup.db /opt/viewtrip/db/viewtripweb.db
   rsync -avz -e "ssh -p 4488" Rui@narciso.synology.me:/volume2/docker/viewtrip/data/ /opt/viewtrip/data/
   rsync -avz -e "ssh -p 4488" Rui@narciso.synology.me:/volume2/docker/viewtrip/config/ /opt/viewtrip/config/
   ```
   **Gotchas encountered:**
   - `scp` alone failed with `subsystem request failed` — modern OpenSSH
     clients default to SFTP-based scp, which Synology's sshd doesn't have
     enabled. Fix: `-O` forces the legacy SCP protocol.
   - Legacy `-O` scp doesn't support the `source_dir/.` trick for copying a
     directory's contents without the directory itself (`unexpected
     filename: .`) — use `rsync` for directories instead.
   - `rsync` wasn't runnable on the NAS until DSM's **Control Panel > File
     Services > rsync** service was explicitly enabled (installs/activates
     the `rsync` binary as a side effect, even though the connection here
     tunnels through SSH rather than using the native daemon protocol).
   - Ensure destination ownership is correct first (`sudo chown -R
     $USER:$USER /opt/viewtrip`) — Docker can leave bind-mount dirs owned by
     root from an earlier `up`.

4. `cd /opt/viewtrip && docker compose up -d`, then `docker compose logs -f`
   to confirm a clean Alembic migration + startup before checking the site.

## 5. `deploy.ps1`

Added a `-Target Validation|Prod` parameter (default `Validation`, the
existing NAS validation flow — unchanged). `-Target Prod`:

- Skips the Flutter/Docker build entirely — prod runs whatever `:latest` CI
  already published for the current tagged release, not a local build.
- SSHes to the VPS (`164.132.195.154`, user `Rui`, key
  `$HOME\.ssh\traxjourney_vps`) and runs `docker compose down / pull / up -d`
  in `/opt/viewtrip`.

```powershell
.\deploy.ps1 -Target Prod
```

## Open items

- [ ] Off-site backups independent of OVH (the VPS's datacenter, Strasbourg,
      is the same site that suffered OVH's 2021 fire — the in-house
      "Automated Backup" option isn't sufficient on its own).
- [ ] Decommission or keep the NAS deployment as a standing fallback.
