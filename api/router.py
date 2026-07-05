"""Combines all REST API sub-routers into a single FastAPI app."""
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from scalar_fastapi import get_scalar_api_reference

from src.project.project_repo import StaleWriteError

from api.admin import router as admin_router
from api.auth import router as auth_router
from api.backup import router as backup_router
from api.geo import router as geo_router
from api.journal import router as journal_router
from api.memories import router as memories_router
from api.people import router as people_router
from api.polarsteps import router as polarsteps_router
from api.projects import router as projects_router
from api.share import router as share_router
from api.strava import router as strava_router
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from models.project_db import _check_schema_contract
from src.admin.bootstrap import seed_admin
from src.backup.backup_service import backup_db
from src.utils.logging import configure_logging, get_logger

# Wire app loggers (api.*, src.*) to a console handler as early as possible —
# this is the process entry point (uvicorn api.router:app), so configuring here
# means INFO+ logs surface from import time onward, not just inside the lifespan.
configure_logging()

_log = get_logger(__name__)
_scheduler = AsyncIOScheduler()

# Single source of truth for the running version: the git tag baked in at build
# time (Dockerfile ARG/ENV APP_VERSION, set from the tag by CI). Defaults to
# "dev" locally. Used for both the OpenAPI `version` and the /api/version probe.
_APP_VERSION = os.environ.get("APP_VERSION", "dev")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    cfg = AlembicConfig(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    alembic_command.upgrade(cfg, "head")
    _check_schema_contract()
    seed_admin()
    _scheduler.add_job(backup_db, "cron", hour=2, minute=0, id="daily_backup", replace_existing=True)
    _scheduler.start()
    _log.info("Backup scheduler started — daily at 02:00 UTC")
    yield
    _scheduler.shutdown(wait=False)


app = FastAPI(
    title="ViewTrip API",
    description=(
        "REST API consumed by the ViewTrip Flutter client (web, Android, iOS).\n\n"
        "Authentication uses JWT bearer tokens obtained via `/api/auth/token` "
        "(email + password), `/api/auth/register`, or `/api/auth/google`.\n\n"
        "Interactive docs: [`/docs`](/docs) (Swagger) · [`/scalar`](/scalar) (Scalar)"
    ),
    version=_APP_VERSION,
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

app.include_router(admin_router)
app.include_router(auth_router)
app.include_router(backup_router)
app.include_router(geo_router)
app.include_router(journal_router)
app.include_router(memories_router)
app.include_router(people_router)
app.include_router(polarsteps_router)
app.include_router(projects_router)
app.include_router(share_router)
app.include_router(strava_router)


@app.exception_handler(StaleWriteError)
async def _stale_write_handler(_request, exc: StaleWriteError):
    """Map an optimistic-lock conflict to 409 so clients can refetch and retry."""
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.get("/scalar", include_in_schema=False)
async def scalar_docs() -> HTMLResponse:
    """Scalar API reference UI."""
    return get_scalar_api_reference(
        openapi_url="/openapi.json",
        title="ViewTrip API",
    )


@app.get("/api/version", include_in_schema=False)
async def app_version():
    """Version this image was built from (the git tag baked in at build time).

    The web client compares its own baked APP_VERSION against this and prompts a
    reload when they differ, so a returning user never stays stuck on a stale
    cached bundle. Defaults to "dev" locally (matching the client default) so the
    check never fires outside a real deployment.
    """
    return {"version": _APP_VERSION}


# ── Flutter web SPA — must be registered last so /api/... routes take priority ─
_web_dir = os.path.join(os.path.dirname(__file__), "..", "web_client")

_NO_CACHE = "no-cache"
_LONG_CACHE = "public, max-age=86400"


def _cache_control_for(full_path: str) -> str:
    """Cache-Control policy for a Flutter-web asset path.

    Flutter does NOT content-hash its entry-point filenames (``main.dart.js``,
    ``flutter.js``, ``flutter_bootstrap.js``, deferred ``*.part.js``, the service
    worker, ``index.html``, ``manifest.json``, ``version.json``). If any of those
    is allowed to sit in the browser cache, a returning user keeps running the
    *old* build after a deploy — including a stale ``main.dart.js`` that may carry
    a wrong baked API URL — until the cache expires. So every entry point is
    served ``no-cache`` (the browser must revalidate each load; a 304 keeps it
    cheap), guaranteeing the latest build is picked up immediately.

    Only the large, rarely-changing static trees (``assets/`` bundle data,
    ``canvaskit/`` runtime, tied to the Flutter SDK version) get a day of caching.
    """
    if full_path.startswith(("assets/", "canvaskit/")):
        return _LONG_CACHE
    return _NO_CACHE


if os.path.isdir(_web_dir):
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve the Flutter web build; fall back to index.html for SPA routing."""
        candidate = os.path.join(_web_dir, full_path)
        if full_path and os.path.isfile(candidate):
            resp = FileResponse(candidate)
            resp.headers["Cache-Control"] = _cache_control_for(full_path)
            return resp
        resp = FileResponse(os.path.join(_web_dir, "index.html"))
        resp.headers["Cache-Control"] = _NO_CACHE
        return resp
