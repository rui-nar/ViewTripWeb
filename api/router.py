"""Combines all REST API sub-routers into a single FastAPI app."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse

from api.auth import router as auth_router
from api.geo import router as geo_router
from api.journal import router as journal_router
from api.memories import router as memories_router
from api.polarsteps import router as polarsteps_router
from api.projects import router as projects_router
from api.share import router as share_router
from api.strava import router as strava_router
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from models.project_db import _check_schema_contract


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    alembic_command.upgrade(cfg, "head")
    _check_schema_contract()
    yield


app = FastAPI(
    title="ViewTrip API",
    description="REST API consumed by Flutter and other native clients.",
    version="0.14.1",
    lifespan=lifespan,
)

app.add_middleware(GZipMiddleware, minimum_size=1000)

# Allow Flutter dev clients (and web) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(geo_router)
app.include_router(journal_router)
app.include_router(memories_router)
app.include_router(polarsteps_router)
app.include_router(projects_router)
app.include_router(share_router)
app.include_router(strava_router)

# ── Flutter web SPA — must be registered last so /api/... routes take priority ─
_web_dir = os.path.join(os.path.dirname(__file__), "..", "web_client")

_NO_CACHE = "no-cache"
_IMMUTABLE = "public, max-age=31536000, immutable"
_LONG_CACHE = "public, max-age=86400"
# flutter_service_worker.js and flutter_bootstrap.js must not be cached so
# browsers always pick up a new build on next visit.
_NEVER_CACHE = {"flutter_service_worker.js", "flutter_bootstrap.js", "index.html", "manifest.json"}

if os.path.isdir(_web_dir):
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve the Flutter web build; fall back to index.html for SPA routing."""
        candidate = os.path.join(_web_dir, full_path)
        if full_path and os.path.isfile(candidate):
            resp = FileResponse(candidate)
            name = os.path.basename(full_path)
            if name in _NEVER_CACHE:
                resp.headers["Cache-Control"] = _NO_CACHE
            elif full_path.startswith("assets/"):
                # Flutter content-hashes everything under assets/ — safe to cache forever.
                resp.headers["Cache-Control"] = _IMMUTABLE
            elif name.endswith((".js", ".wasm")):
                # main.dart.js / canvaskit.wasm aren't hashed but rarely change mid-session.
                resp.headers["Cache-Control"] = _LONG_CACHE
            else:
                resp.headers["Cache-Control"] = _NO_CACHE
            return resp
        resp = FileResponse(os.path.join(_web_dir, "index.html"))
        resp.headers["Cache-Control"] = _NO_CACHE
        return resp
