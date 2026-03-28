#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build, push and deploy ViewTripWeb to the Synology NAS.

.DESCRIPTION
    1. Builds the Docker image from the repo root.
    2. Tags it with the current git tag (e.g. v0.8.0) AND :latest.
    3. Pushes both tags to GHCR (ghcr.io/rui-nar/viewtripweb).
    4. SSHes into the NAS, pulls the new image, replaces the running
       container — preserving all persistent volumes.

.PREREQUISITES
    - Docker Desktop running locally and logged in to GHCR:
          echo $env:GHCR_TOKEN | docker login ghcr.io -u rui-nar --password-stdin
      (GHCR_TOKEN = a GitHub PAT with write:packages scope)
    - SSH key auth to narciso.synology.me:4488 for user Rui, OR be ready
      to type the password when prompted.
    - On the NAS, Docker must be logged in to GHCR (one-time setup):
          ssh -p 4488 Rui@narciso.synology.me \
            "echo YOUR_PAT | docker login ghcr.io -u rui-nar --password-stdin"
      Store the PAT at $NAS_BASE/secrets/ghcr_token to have the script
      re-authenticate automatically on each deploy.

.PARAMETER Version
    Override the version tag (default: latest annotated git tag).

.EXAMPLE
    .\deploy.ps1
    .\deploy.ps1 -Version v0.9.0
#>
param(
    [string]$Version = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Configuration ─────────────────────────────────────────────────────────────
$IMAGE          = "ghcr.io/rui-nar/viewtripweb"
$NAS_HOST       = "narciso.synology.me"
$NAS_SSH_PORT   = 4488
$NAS_USER       = "Rui"
$NAS_BASE       = "/volume2/mydev/ViewTrip"
$HOST_PORT      = 7777
$CONTAINER_PORT = 8000
$FRONTEND_ORIGIN = "https://viewtrip.narciso.synology.me"
# ──────────────────────────────────────────────────────────────────────────────

function Step([string]$n, [string]$total, [string]$msg) {
    Write-Host ""
    Write-Host "[$n/$total] $msg" -ForegroundColor Cyan
}

function Die([string]$msg) {
    Write-Host ""
    Write-Host "ERROR: $msg" -ForegroundColor Red
    exit 1
}

# Resolve version
if (-not $Version) {
    $Version = git describe --tags --abbrev=0 2>&1
    if ($LASTEXITCODE -ne 0) { Die "No git tag found. Run 'git tag v0.x.0' or pass -Version." }
    $Version = $Version.Trim()
}

Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  ViewTripWeb  ·  deploy $Version" -ForegroundColor Green
Write-Host "  → $IMAGE" -ForegroundColor Green
Write-Host "  → ${NAS_HOST}:${HOST_PORT}" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green

# ── 1. Build ──────────────────────────────────────────────────────────────────
Step 1 3 "Building Docker image..."
docker build -t "${IMAGE}:${Version}" -t "${IMAGE}:latest" .
if ($LASTEXITCODE -ne 0) { Die "docker build failed." }

# ── 2. Push to GHCR ───────────────────────────────────────────────────────────
Step 2 3 "Pushing to GHCR..."
docker push "${IMAGE}:${Version}"
if ($LASTEXITCODE -ne 0) { Die "docker push ${Version} failed." }
docker push "${IMAGE}:latest"
if ($LASTEXITCODE -ne 0) { Die "docker push latest failed." }

# ── 3. Deploy on NAS ──────────────────────────────────────────────────────────
Step 3 3 "Deploying on NAS ($NAS_HOST)..."

# Build the remote bash script as a here-string.
# PowerShell expands $NAS_BASE/$IMAGE/$Version etc. (our local vars).
# Bash variables are escaped with backtick-$ so PowerShell leaves them literal.
$remoteScript = @"
set -euo pipefail

BASE="$NAS_BASE"
IMAGE="$IMAGE"
VERSION="$Version"
HOST_PORT="$HOST_PORT"
CONTAINER_PORT="$CONTAINER_PORT"
FRONTEND_ORIGIN="$FRONTEND_ORIGIN"

# ── Directories ────────────────────────────────────────────────────────────
mkdir -p "`$BASE/db" "`$BASE/config" "`$BASE/data" "`$BASE/secrets"

# ── GHCR login (reads stored PAT if present) ───────────────────────────────
if [ -f "`$BASE/secrets/ghcr_token" ]; then
    echo "  Logging in to GHCR..."
    cat "`$BASE/secrets/ghcr_token" | docker login ghcr.io -u rui-nar --password-stdin
fi

# ── Generate JWT secret on first deploy ────────────────────────────────────
if [ ! -f "`$BASE/secrets/jwt_secret" ]; then
    echo "  Generating JWT secret..."
    if command -v openssl >/dev/null 2>&1; then
        openssl rand -hex 32 > "`$BASE/secrets/jwt_secret"
    else
        tr -dc 'A-Za-z0-9' </dev/urandom | head -c 64 > "`$BASE/secrets/jwt_secret"
    fi
    chmod 600 "`$BASE/secrets/jwt_secret"
    echo "  JWT secret saved to `$BASE/secrets/jwt_secret"
fi
JWT_SECRET=`$(cat "`$BASE/secrets/jwt_secret")

# ── Pull new image ─────────────────────────────────────────────────────────
echo "  Pulling `${IMAGE}:`${VERSION} ..."
docker pull "`${IMAGE}:`${VERSION}"
docker tag  "`${IMAGE}:`${VERSION}" "`${IMAGE}:latest"

# ── Stop and remove existing container ────────────────────────────────────
if docker ps -a --format '{{.Names}}' | grep -q '^viewtripweb`$'; then
    echo "  Stopping existing container..."
    docker stop viewtripweb >/dev/null
    docker rm   viewtripweb >/dev/null
fi

# ── Start new container ────────────────────────────────────────────────────
echo "  Starting container..."
docker run -d \
  --name viewtripweb \
  --restart unless-stopped \
  -p "`${HOST_PORT}:`${CONTAINER_PORT}" \
  -v "`$BASE/db:/app/db" \
  -v "`$BASE/config:/app/config" \
  -v "`$BASE/data:/app/data" \
  -e DATABASE_URL="sqlite:////app/db/viewtripweb.db" \
  -e JWT_SECRET="`$JWT_SECRET" \
  -e FRONTEND_ORIGIN="`$FRONTEND_ORIGIN" \
  -e STRAVA_REDIRECT_URI="`$FRONTEND_ORIGIN/api/strava/callback" \
  "`${IMAGE}:latest" >/dev/null

# ── Health check ───────────────────────────────────────────────────────────
sleep 2
echo ""
docker ps --filter name=viewtripweb --format "  container : {{.Names}}"
docker ps --filter name=viewtripweb --format "  status    : {{.Status}}"
docker ps --filter name=viewtripweb --format "  ports     : {{.Ports}}"

# ── Remove dangling images to free disk space ──────────────────────────────
docker image prune -f >/dev/null 2>&1 || true

echo ""
echo "  Done."
"@

# Pipe the script into bash over SSH
$remoteScript | ssh -p $NAS_SSH_PORT "${NAS_USER}@${NAS_HOST}" "bash -s"
if ($LASTEXITCODE -ne 0) { Die "Remote deployment failed." }

Write-Host ""
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host "  Deployed $Version" -ForegroundColor Green
Write-Host "  API (direct) : http://${NAS_HOST}:${HOST_PORT}" -ForegroundColor Green
Write-Host "  App (proxy)  : $FRONTEND_ORIGIN" -ForegroundColor Green
Write-Host "  Reverse proxy → ${NAS_HOST}:${HOST_PORT}" -ForegroundColor Green
Write-Host "═══════════════════════════════════════════" -ForegroundColor Green
Write-Host ""
