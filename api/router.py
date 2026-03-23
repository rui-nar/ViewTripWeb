"""Combines all REST API sub-routers into a single FastAPI app."""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.auth import router as auth_router
from api.geo import router as geo_router
from api.projects import router as projects_router
from api.strava import router as strava_router

api = FastAPI(
    title="ViewTrip API",
    description="REST API consumed by Flutter and other native clients.",
    version="1.0.0",
)

# Allow Flutter dev clients (and web) to call the API
api.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

api.include_router(auth_router)
api.include_router(geo_router)
api.include_router(projects_router)
api.include_router(strava_router)
