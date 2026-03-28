"""Combines all REST API sub-routers into a single FastAPI app."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from api.geo import router as geo_router
from api.projects import router as projects_router
from api.share import router as share_router
from api.strava import router as strava_router

app = FastAPI(
    title="ViewTrip API",
    description="REST API consumed by Flutter and other native clients.",
    version="1.0.0",
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
