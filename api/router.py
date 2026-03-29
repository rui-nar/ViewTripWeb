"""Combines all REST API sub-routers into a single FastAPI app."""
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from api.auth import router as auth_router
from api.geo import router as geo_router
from api.projects import router as projects_router
from api.share import router as share_router
from api.strava import router as strava_router

app = FastAPI(
    title="ViewTrip API",
    description="REST API consumed by Flutter and other native clients.",
    version="0.8.3",
)

# Allow Flutter dev clients (and web) to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(geo_router)
app.include_router(projects_router)
app.include_router(share_router)
app.include_router(strava_router)

# ── Flutter web SPA — must be registered last so /api/... routes take priority ─
_web_dir = os.path.join(os.path.dirname(__file__), "..", "web_client")

if os.path.isdir(_web_dir):
    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str):
        """Serve the Flutter web build; fall back to index.html for SPA routing."""
        candidate = os.path.join(_web_dir, full_path)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(os.path.join(_web_dir, "index.html"))
