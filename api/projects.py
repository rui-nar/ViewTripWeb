"""REST projects endpoints — list, create, open, delete, and manage projects.

Routes:
    GET    /api/projects/                       — list saved projects for current user
    POST   /api/projects/                       — create new project
    GET    /api/projects/{name}                 — get project data (GeoJSON + metadata)
    DELETE /api/projects/{name}                 — delete a project
    POST   /api/projects/import                 — upload a .viewtrip file
    GET    /api/projects/{name}/export          — download project as GPX file
    GET    /api/projects/{name}/export-viewtrip — download project as .viewtrip JSON
    GET    /api/projects/{name}/export-zip      — download ZIP (.viewtrip + photos)
    POST   /api/projects/{name}/activities      — add activities to project
    DELETE /api/projects/{name}/items/{index}   — remove item at index
    PUT    /api/projects/{name}/items/reorder   — move item from/to index
    POST   /api/projects/{name}/segments        — create a connecting segment
    PUT    /api/projects/{name}/segments/{id}   — update a segment
    DELETE /api/projects/{name}/segments/{id}   — delete a segment
"""
from __future__ import annotations

import io
import json
import os
import re
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import gpxpy
import gpxpy.gpx
import polyline as polyline_lib
from models.db import get_session
from sqlmodel import select

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.geo import bust_geo_cache, warm_geo_cache
from models.project_db import DBProject, DBProjectItem, DBProjectSyncMeta, DBShareVisit
from models.user import UserInfo, PolarstepsToken, StravaToken
from src.api.polarsteps_client import PolarstepsClient, format_step
from src.api.strava_client import RateLimiter, StravaAPI
from src.config.settings import Config
from src.models.activity import Activity
from src.models.great_circle import great_circle_points
from src.models.project import ConnectingSegment, DEFAULT_SLEEPING_GROUPS, ProjectItem, SegmentEndpoint
from src.project.project_io import ProjectIO
from src.project.project_repo import ProjectRepo, StaleWriteError, _compute_stats
from src.utils.logging import get_logger

_log = get_logger(__name__)

_cfg = Config("config/config.json")
if os.environ.get("STRAVA_CLIENT_ID"):
    _cfg.set("strava.client_id", os.environ["STRAVA_CLIENT_ID"])
if os.environ.get("STRAVA_CLIENT_SECRET"):
    _cfg.set("strava.client_secret", os.environ["STRAVA_CLIENT_SECRET"])
_repo = ProjectRepo()

router = APIRouter(prefix="/api/projects", tags=["projects"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


# ── Response schemas ──────────────────────────────────────────────────────────

class ProjectCreatedOut(BaseModel):
    name: str = Field(description="Final project name (may differ if trimmed)")
    filename: str = Field(description="Backing filename for legacy file-based access")

class ProjectUpdatedOut(BaseModel):
    name: str = Field(description="Project name after update (reflects any rename)")
    trip_start: Optional[str] = Field(None, description="Trip start date (YYYY-MM-DD) or null")

class SyncMetaOut(BaseModel):
    auto_sync_enabled: bool = Field(description="Whether auto-sync is active for this project")
    linked_ps_trip_id: Optional[int] = Field(None, description="Linked Polarsteps trip ID, or null")
    last_strava_sync_at: Optional[float] = Field(None, description="Unix timestamp of last Strava sync")
    last_ps_sync_at: Optional[float] = Field(None, description="Unix timestamp of last Polarsteps sync")

class SegmentIDOut(BaseModel):
    id: str = Field(description="UUID of the newly created segment")

class ShareTokenOut(BaseModel):
    share_token: str = Field(description="Public share token for full-project access")

class ShareTokenNoMemoriesOut(BaseModel):
    share_token_no_memories: str = Field(description="Public share token with memories stripped")

class ShareInfoOut(BaseModel):
    share_token: Optional[str] = Field(None, description="Full-access share token, or null if not created")
    share_token_no_memories: Optional[str] = Field(None, description="No-memories share token, or null if not created")

class ActivitiesAddedOut(BaseModel):
    added: int = Field(description="Number of new activities added")
    total: int = Field(description="Total activities in the project after add")
    pending_enrichment: int = Field(description="Activities queued for GPS stream enrichment in background")

class RouteResolvedOut(BaseModel):
    polyline: List[List[float]] = Field(description="Resolved route as [[lon, lat], …] coordinates")
    stop_count: int = Field(description="Number of intermediate stops on the route")


class RouteResolveTriggered(BaseModel):
    """Returned by the async resolve-route trigger (HTTP 202)."""
    status: str = Field(description="Always 'pending' — resolution runs in the background")
    route_status: str = Field(description="Segment route_status after scheduling: 'pending'")

class ImportedOut(BaseModel):
    name: str = Field(description="Name of the imported project")


def _refresh_share_tiles(user_info_id: int, project_name: str) -> None:
    """Re-render raster tiles for any active share token(s) after a project mutation."""
    from api.share import _build_features, invalidate_share_cache
    from src.tile_renderer import refresh_tile_cache

    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == project_name,
            )
        ).first()
    if row is None:
        return
    tokens = [t for t in (row.share_token, row.share_token_no_memories) if t]
    if not tokens:
        return

    for token in tokens:
        invalidate_share_cache(token)

    with get_session() as sess:
        project = _repo.get_project_by_id(sess, row.id)
    if project is None:
        return
    features = _build_features(project)

    for token in tokens:
        refresh_tile_cache(token, lambda f=features: f)


def _projects_dir(user_id: str) -> str:
    path = os.path.join(_DATA_DIR, "users", user_id, "projects")
    os.makedirs(path, exist_ok=True)
    return path


def _legacy_path(user_id: str, name: str) -> str:
    return os.path.join(_projects_dir(user_id), name + ProjectIO.EXTENSION)


# ── Strava stream enrichment ───────────────────────────────────────────────────

def _strava_client_for_user(user_info_id: int) -> Optional[StravaAPI]:
    """Return a StravaAPI instance for the given user, or None if not connected."""
    with get_session() as sess:
        token_row = sess.exec(
            select(StravaToken).where(StravaToken.user_info_id == user_info_id)
        ).first()
        if not token_row:
            return None
    client = StravaAPI(_cfg)
    client.token_data = {
        "access_token":  token_row.access_token,
        "refresh_token": token_row.refresh_token,
        "expires_at":    token_row.expires_at,
    }
    return client


def _enrich_activities(
    activities: List[Activity],
    client: StravaAPI,
) -> List[Activity]:
    """Fetch streams for each activity, enriching summary_polyline and elevation_profile in-place.

    Returns any activities that could not be enriched due to rate limiting.
    """
    pending: List[Activity] = []
    for act in activities:
        if act.id is None:
            continue
        if act.is_edited:
            continue  # locally edited track — never overwrite from Strava
        if client.remaining_requests <= 2:
            pending.append(act)
            continue
        try:
            streams  = client.get_activity_streams(act.id)
            latlng   = streams.get("latlng",   {}).get("data") or []
            altitude = streams.get("altitude", {}).get("data") or []
            distance = streams.get("distance", {}).get("data") or []

            if latlng:
                act.summary_polyline = polyline_lib.encode(
                    [(pt[0], pt[1]) for pt in latlng]
                )
                if not act.start_latlng:
                    act.start_latlng = [latlng[0][0], latlng[0][1]]
                if not act.end_latlng:
                    act.end_latlng = [latlng[-1][0], latlng[-1][1]]
            n = min(len(altitude), len(distance))
            if n >= 2:
                act.elevation_profile = (
                    [distance[i] / 1000 for i in range(n)],
                    [altitude[i]        for i in range(n)],
                )
        except Exception:
            pass  # private activity or network error — skip silently
    return pending


def _enrich_activities_background(
    activity_ids: List[int],
    user_info_id: int,
    project_name: str,
) -> None:
    """Enrich GPS streams for newly imported activities in the background.

    Starts immediately (no sleep) so the response is never blocked.  Each
    activity is written to the DB as it completes so partial progress is
    preserved on interruption.  Strava 429 responses are handled by the
    StravaAPI client (sleeps Retry-After then continues).
    """
    client = _strava_client_for_user(user_info_id)
    if client is None:
        return

    any_enriched = False
    for activity_id in activity_ids:
        if _repo.activity_is_edited(activity_id):
            continue  # locally edited track — never overwrite from Strava
        try:
            streams  = client.get_activity_streams(activity_id)
            latlng   = streams.get("latlng",   {}).get("data") or []
            altitude = streams.get("altitude", {}).get("data") or []
            distance = streams.get("distance", {}).get("data") or []

            polyline_str: Optional[str] = None
            ep_json: Optional[str] = None

            if latlng:
                polyline_str = polyline_lib.encode([(pt[0], pt[1]) for pt in latlng])
            n = min(len(altitude), len(distance))
            if n >= 2:
                ep_json = json.dumps({
                    "distances_km": [distance[i] / 1000 for i in range(n)],
                    "elevations_m": [altitude[i]        for i in range(n)],
                })

            if polyline_str or ep_json:
                with get_session() as sess:
                    _repo.update_activity_enrichment(
                        sess, activity_id, polyline_str, ep_json
                    )
                any_enriched = True
        except Exception:
            pass

    if any_enriched:
        bust_geo_cache(user_info_id, project_name)
        # Recompute now (still in the background task) so the user's next geo
        # load is a fast cache HIT rather than a cold recompute.
        warm_geo_cache(user_info_id, project_name)


def _enrich_pending_background(
    pending_ids: List[int],
    user_info_id: int,
    project_name: str,
) -> None:
    """Sleep until the Strava rate-limit window resets, then enrich remaining activities."""
    time.sleep(RateLimiter.WINDOW_SECONDS + 5)
    _enrich_activities_background(pending_ids, user_info_id, project_name)


def _refresh_stats_background(user_info_id: int, project_name: str) -> None:
    """Background task: open a fresh session and recompute project stats."""
    with get_session() as sess:
        _repo.compute_and_cache_stats(sess, user_info_id, project_name)


def _compute_segment_geometry(
    seg: ConnectingSegment, params: Dict[str, Any]
) -> tuple[list, int, bool, str]:
    """Run the (slow) HAFAS + Overpass lookups for a segment.

    Returns ``(polyline, stop_count, degraded, strategy)``.  ``degraded`` is True
    only for rail when every Overpass strategy failed and the result is a straight
    endpoint chord — the line is approximate, not real track.  Ferry/bus raise
    ``OverpassError`` on failure (never degrade), so their ``degraded`` is always
    False.  ``strategy`` names how the geometry was obtained (for logging).
    """
    from src.services.overpass_service import (
        OverpassError,  # noqa: F401 — re-exported for callers' except clauses
        get_bus_geometry,
        get_ferry_geometry,
        get_rail_geometry,
    )

    if seg.segment_type == "train":
        from src.services.hafas_service import HafasError, get_stop_sequence

        use_date = params.get("date") or seg.date
        stops: list[dict] = [
            {"lat": seg.start.lat, "lon": seg.start.lon},
            {"lat": seg.end.lat,   "lon": seg.end.lon},
        ]
        if params.get("hafas_provider") and params.get("train_number"):
            try:
                stops = get_stop_sequence(
                    provider=params["hafas_provider"],
                    train_number=params["train_number"],
                    date=use_date or "",
                    start_lat=seg.start.lat, start_lon=seg.start.lon,
                    end_lat=seg.end.lat,     end_lon=seg.end.lon,
                )
            except HafasError:
                pass  # fall back to two-point geometry
        rail = get_rail_geometry(stops)
        return rail.polyline, len(stops), rail.degraded, rail.strategy

    if seg.segment_type == "boat":
        polyline = get_ferry_geometry(
            seg.start.lat, seg.start.lon, seg.end.lat, seg.end.lon)
        return polyline, 2, False, "ferry"

    if seg.segment_type == "bus":
        polyline = get_bus_geometry(
            seg.start.lat, seg.start.lon, seg.end.lat, seg.end.lon)
        return polyline, 2, False, "bus"

    raise ValueError("Route resolution only supported for train, boat, and bus segments")


def _find_segment(project, seg_id: str):
    return next(
        (i.segment for i in project.items
         if i.item_type == "segment" and i.segment and i.segment.id == seg_id),
        None,
    )


def _resolve_route_job(
    user_info_id: int, name: str, seg_id: str, params: Dict[str, Any]
) -> None:
    """Background task: resolve a segment's real-world route geometry.

    Runs the long HAFAS + Overpass lookups off the request path (holding no DB
    session during the slow work), then persists the result with an
    optimistic-lock retry so a concurrent user edit can't be silently clobbered.
    Mirrors the fire-and-forget pattern of :func:`_refresh_share_tiles`.
    """
    _mode_for_type = {"train": "rail", "boat": "ferry", "bus": "bus"}
    try:
        # 1. Load the segment (cheap) and compute geometry with no session held.
        with get_session() as sess:
            project = _repo.get_project(sess, user_info_id, name)
        if project is None:
            return
        seg = _find_segment(project, seg_id)
        if seg is None:
            return
        try:
            polyline, _stops, degraded, strategy = _compute_segment_geometry(seg, params)
            outcome = ("resolved", json.dumps(polyline),
                       _mode_for_type.get(seg.segment_type, "great_circle"), None, degraded)
            _log.info(
                "resolve seg=%s type=%s strategy=%s points=%d degraded=%s status=resolved",
                seg_id, seg.segment_type, strategy, len(polyline), degraded)
        except Exception as exc:  # noqa: BLE001 — any failure marks the segment failed
            outcome = ("failed", None, None, str(exc)[:200] or "Route resolution failed", False)
            _log.warning("resolve seg=%s type=%s status=failed: %s",
                         seg_id, seg.segment_type, exc)

        # 2. Persist, retrying once if a concurrent write bumped the lock_version.
        for attempt in range(2):
            try:
                with get_session() as sess:
                    project = _repo.get_project(sess, user_info_id, name)
                    if project is None:
                        return
                    seg = _find_segment(project, seg_id)
                    if seg is None:
                        return  # deleted mid-resolve — nothing to write
                    status, poly_json, rmode, err, degraded = outcome
                    if status == "resolved":
                        seg.route_mode = rmode
                        seg.route_polyline = poly_json
                        seg.route_status = "resolved"
                        seg.route_error = None
                        seg.route_degraded = degraded
                        if params.get("train_number"):
                            seg.train_number = params["train_number"]
                        if params.get("hafas_provider"):
                            seg.hafas_provider = params["hafas_provider"]
                    else:
                        # Leave route_mode/route_polyline so geo still renders the
                        # great-circle arc; surface a short error for the UI.
                        seg.route_status = "failed"
                        seg.route_error = err
                        seg.route_degraded = False
                    seg.route_started_at = None
                    _repo.save_project(sess, user_info_id, project, check_version=True)
                break
            except StaleWriteError:
                if attempt == 1:
                    break  # give up — a later edit/poll will reflect reality
                continue
    except Exception as exc:  # noqa: BLE001
        # The segment was marked "pending" synchronously by the trigger. If the
        # job crashes anywhere above (a load/save error, an unexpected raise),
        # nothing writes a terminal status and the segment stays "pending"
        # forever — a frozen spinner the client's stale-recovery only re-triggers
        # into the same crash. Best-effort flip it to "failed" so the user sees an
        # error they can retry, and log the cause (the prod 500/stuck-pending bug).
        _log.exception("resolve seg=%s crashed before persisting a verdict", seg_id)
        _mark_segment_failed(user_info_id, name, seg_id, str(exc)[:200])
    finally:
        bust_geo_cache(user_info_id, name)
        # Warm the cache while still off the request path so returning to the
        # project after a resolve is a fast HIT, not a cold recompute that can
        # time out and leave activities as low-res straight lines.
        warm_geo_cache(user_info_id, name)


def _mark_segment_failed(user_info_id: int, name: str, seg_id: str, err: str) -> None:
    """Best-effort: flip a still-``pending`` segment to ``failed`` after a crash.

    Wrapped so it can never raise out of the job's except handler. If the segment
    is gone or already terminal, it's a no-op; if the save itself fails (e.g. the
    very DB error that crashed the job), we log and give up — the client's
    stale-pending recovery remains the last line of defence.
    """
    try:
        with get_session() as sess:
            project = _repo.get_project(sess, user_info_id, name)
            if project is None:
                return
            seg = _find_segment(project, seg_id)
            if seg is None or seg.route_status != "pending":
                return
            seg.route_status = "failed"
            seg.route_error = err or "Route resolution failed"
            seg.route_started_at = None
            seg.route_degraded = False
            _repo.save_project(sess, user_info_id, project, check_version=True)
    except Exception:  # noqa: BLE001
        _log.exception("could not mark seg=%s failed after a crashed resolve", seg_id)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", summary="List projects")
def list_projects(current_user: Annotated[dict, Depends(get_current_user)]):
    """Return all projects belonging to the current user."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        return _repo.list_projects(sess, user_info_id)


class CreateProjectRequest(BaseModel):
    name: str


@router.post("/", status_code=status.HTTP_201_CREATED, response_model=ProjectCreatedOut,
             summary="Create a project")
def create_project(
    body: CreateProjectRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    name = body.name.strip() or "My Trip"
    with get_session() as sess:
        if _repo.project_exists(sess, user_info_id, name):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Project '{name}' already exists",
            )
        _repo.create_project(sess, user_info_id, name)
    return {"name": name, "filename": name + ProjectIO.EXTENSION}


@router.get("/{name}", summary="Get full project data")
def get_project(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _repo.to_dict(project)


@router.get("/{name}/meta", summary="Get project metadata (lightweight)")
def get_project_meta(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Same shape as GET /{name} but with elevation_profile and map.summary_polyline
    absent from each activity.  Uses lightweight loading (deferred heavy columns) so
    cold-cache response time is under 1 s even on spinning-disk NAS storage.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
            include_heavy=False,
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return _repo.to_dict(project)


@router.get("/{name}/stats", summary="Get project statistics")
def get_project_stats(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    tags: Optional[List[str]] = Query(default=None),
):
    """Return project statistics, optionally filtered to days with matching tags."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        if tags:
            # Tag-filtered request: compute on-demand (bypass cache)
            project = _repo.get_project(sess, user_info_id, name)
            if project is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
            return _compute_stats(project, tag_filter=tags)

        # Unfiltered: use cached stats
        if row.stats_json is None:
            _repo.compute_and_cache_stats(sess, user_info_id, name)
            row = sess.exec(
                select(DBProject).where(
                    DBProject.user_info_id == user_info_id,
                    DBProject.name == name,
                )
            ).first()
        stats = json.loads(row.stats_json or "{}")

        # Always derive tag_options live from day_meta_json so they are never
        # stale (cached stats pre-date the tag-save fix and stored [] here).
        stats["tag_options"] = sorted({
            t
            for dm in json.loads(row.day_meta_json or "{}").values()
            for t in (dm.get("tags") or [])
        })
    return stats


class ProjectUpdateRequest(BaseModel):
    new_name: Optional[str] = None
    trip_start: Optional[str] = None  # "YYYY-MM-DD" or None to clear
    trip_end: Optional[str] = None    # "YYYY-MM-DD" or None to clear


@router.put("/{name}", response_model=ProjectUpdatedOut, summary="Update project name or dates")
def update_project(
    name: str,
    body: ProjectUpdateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        # Rename if requested
        if body.new_name is not None:
            new_name = body.new_name.strip()
            if not new_name:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Name cannot be empty")
            if new_name != name and _repo.project_exists(sess, user_info_id, new_name):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Project '{new_name}' already exists")
            row.name = new_name

        # Update trip_start if key is present in body (None = clear)
        if 'trip_start' in body.model_fields_set:
            row.trip_start = body.trip_start or None

        # Update trip_end if key is present in body (None = clear)
        if 'trip_end' in body.model_fields_set:
            row.trip_end = body.trip_end or None

        sess.add(row)
        sess.commit()
        result_name = row.name
        result_trip_start = row.trip_start
    return {"name": result_name, "trip_start": result_trip_start}


class DayMetaUpdateRequest(BaseModel):
    day_meta: Dict[str, Dict[str, Any]]
    sleeping_options: Optional[List[str]] = None
    sleeping_option_groups: Optional[Dict[str, str]] = None  # name → "Outdoors"|"Indoors"|"Other"
    counters: Optional[List[Dict[str, Any]]] = None  # [{name, start}]


def _merge_day_meta_preserve_counters(incoming: dict, existing_json: str | None) -> dict:
    """Return incoming day_meta with existing per-day counter values preserved.

    If a day in the stored row has counters but the incoming dict for that day
    omits the "counters" key entirely, the stored counters are copied across.
    Sending "counters": {} explicitly clears them (caller's intent wins).

    This protects against a Flutter app saving settings from a session that
    started before an enrichment script added counter values.
    """
    existing = json.loads(existing_json) if existing_json else {}
    merged = dict(incoming)
    for date_key, existing_day in existing.items():
        existing_counters = existing_day.get("counters")
        if existing_counters:
            incoming_day = merged.get(date_key)
            if incoming_day is not None and "counters" not in incoming_day:
                incoming_day["counters"] = existing_counters
    return merged


@router.put("/{name}/day-meta", status_code=status.HTTP_204_NO_CONTENT,
            summary="Update day metadata")
def update_day_meta(
    name: str,
    body: DayMetaUpdateRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Replace day metadata (and optionally sleeping options) for a project."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        row.day_meta_json = json.dumps(
            _merge_day_meta_preserve_counters(body.day_meta, row.day_meta_json)
        )
        if body.sleeping_options:  # ignore empty list — never wipe sleeping options
            groups = body.sleeping_option_groups or {}
            row.sleeping_options_json = json.dumps([
                {"name": n, "group": groups.get(n, DEFAULT_SLEEPING_GROUPS.get(n, 'Other'))}
                for n in body.sleeping_options
            ])
        if body.counters is not None:
            row.counters_json = json.dumps([
                {"name": c["name"], "start": float(c.get("start", 0))}
                for c in body.counters
            ])
        row.updated_at = time.time()
        sess.add(row)
        sess.commit()
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)


# ── Sync-meta (auto-sync config per project) ─────────────────────────────────

def _get_sync_meta(sess, project_id: int) -> DBProjectSyncMeta:
    """Return the sync-meta row for a project, creating a default if absent."""
    row = sess.get(DBProjectSyncMeta, project_id)
    if row is None:
        row = DBProjectSyncMeta(project_id=project_id)
    return row


def _get_project_row(sess, user_info_id: int, name: str) -> DBProject:
    row = sess.exec(
        select(DBProject).where(
            DBProject.user_info_id == user_info_id,
            DBProject.name == name,
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return row


@router.get("/{name}/sync-meta", response_model=SyncMetaOut, summary="Get sync configuration")
def get_sync_meta(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        proj = _get_project_row(sess, user_info_id, name)
        meta = _get_sync_meta(sess, proj.id)
    return {
        "auto_sync_enabled": meta.auto_sync_enabled,
        "linked_ps_trip_id": meta.linked_ps_trip_id,
        "last_strava_sync_at": meta.last_strava_sync_at,
        "last_ps_sync_at": meta.last_ps_sync_at,
    }


class TrackStyleUpdateRequest(BaseModel):
    track_color: Optional[str] = None           # "#RRGGBB" hex
    track_secondary_color: Optional[str] = None  # "#RRGGBB" hex; null = auto-derive
    track_width: Optional[float] = None
    alternating_track_colors: Optional[bool] = None
    elevation_chart_color: Optional[str] = None  # "#RRGGBB" hex; null = use default
    elevation_chart_show_line: Optional[bool] = None


@router.put("/{name}/track-style", status_code=status.HTTP_204_NO_CONTENT,
            summary="Update track style")
def update_track_style(
    name: str,
    body: TrackStyleUpdateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> None:
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_project_row(sess, user_info_id, name)
        if body.track_color is not None:
            row.track_color = body.track_color
        if 'track_secondary_color' in body.model_fields_set:
            row.track_secondary_color = body.track_secondary_color
        if body.track_width is not None:
            row.track_width = body.track_width
        if body.alternating_track_colors is not None:
            row.alternating_track_colors = body.alternating_track_colors
        if 'elevation_chart_color' in body.model_fields_set:
            row.elevation_chart_color = body.elevation_chart_color
        if body.elevation_chart_show_line is not None:
            row.elevation_chart_show_line = body.elevation_chart_show_line
        row.updated_at = time.time()
        sess.add(row)
        sess.commit()


class LanguagesUpdateRequest(BaseModel):
    languages: List[str]  # ISO 639-1 codes, e.g. ["fr", "de"]


@router.put("/{name}/languages", status_code=status.HTTP_204_NO_CONTENT,
            summary="Update translation languages")
def update_languages(
    name: str,
    body: LanguagesUpdateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> None:
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_project_row(sess, user_info_id, name)
        row.languages_json = json.dumps(body.languages)
        row.updated_at = time.time()
        sess.add(row)
        sess.commit()


class SyncMetaUpdateRequest(BaseModel):
    auto_sync_enabled: Optional[bool] = None
    linked_ps_trip_id: Optional[int] = None
    last_strava_sync_at: Optional[float] = None
    last_ps_sync_at: Optional[float] = None


@router.put("/{name}/sync-meta", response_model=SyncMetaOut, summary="Update sync configuration")
def update_sync_meta(
    name: str,
    body: SyncMetaUpdateRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        proj = _get_project_row(sess, user_info_id, name)
        meta = _get_sync_meta(sess, proj.id)
        if meta.project_id != proj.id:
            meta.project_id = proj.id
        if body.auto_sync_enabled is not None:
            meta.auto_sync_enabled = body.auto_sync_enabled
        if 'linked_ps_trip_id' in body.model_fields_set:
            meta.linked_ps_trip_id = body.linked_ps_trip_id
        if body.last_strava_sync_at is not None:
            meta.last_strava_sync_at = body.last_strava_sync_at
        if body.last_ps_sync_at is not None:
            meta.last_ps_sync_at = body.last_ps_sync_at
        sess.add(meta)
        sess.commit()
        # Read attributes BEFORE the session closes. After commit the instance is
        # expired (expire_on_commit=True), so touching meta.* outside the `with`
        # block raises DetachedInstanceError.
        result = {
            "auto_sync_enabled": meta.auto_sync_enabled,
            "linked_ps_trip_id": meta.linked_ps_trip_id,
            "last_strava_sync_at": meta.last_strava_sync_at,
            "last_ps_sync_at": meta.last_ps_sync_at,
        }
    return result


@router.get("/{name}/sync/check", summary="Check for new activities to sync")
def sync_check(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> dict:
    """Return new Strava activities and Polarsteps steps not yet in this project."""
    user_info_id = int(current_user["sub"])

    with get_session() as sess:
        proj = _get_project_row(sess, user_info_id, name)
        meta = _get_sync_meta(sess, proj.id)

        if not meta.auto_sync_enabled:
            return {"strava": [], "polarsteps": []}

        # ── Strava ────────────────────────────────────────────────────────────
        strava_results: List[Dict[str, Any]] = []
        strava_token = sess.exec(
            select(StravaToken).where(StravaToken.user_info_id == user_info_id)
        ).first()

        if strava_token and strava_token.access_token:
            from api.strava import _load_cache, _strava_client_for_token, _fetch_all_strava, _save_cache, _save_refreshed_token

            raw_list: Optional[List[Dict[str, Any]]] = None
            cache_data = _load_cache(user_info_id)
            if cache_data is not None:
                raw_list = cache_data["activities"]
            else:
                try:
                    client = _strava_client_for_token(strava_token)
                    raw_list = _fetch_all_strava(client)
                    _save_cache(user_info_id, raw_list)
                    _save_refreshed_token(sess, strava_token, client)
                except Exception:
                    raw_list = []

            if raw_list:
                # Parse + filter by last_strava_sync_at and trip date range
                cutoff = meta.last_strava_sync_at or 0.0
                trip_start_date = (
                    datetime.strptime(proj.trip_start, "%Y-%m-%d").date()
                    if proj.trip_start else None
                )
                trip_end_date = (
                    datetime.strptime(proj.trip_end, "%Y-%m-%d").date()
                    if proj.trip_end else None
                )
                # Get IDs already in project
                item_rows = sess.exec(
                    select(DBProjectItem).where(
                        DBProjectItem.project_id == proj.id,
                        DBProjectItem.item_type == "activity",
                    )
                ).all()
                in_project_ids = {r.activity_id for r in item_rows if r.activity_id is not None}

                for raw in raw_list:
                    try:
                        act = Activity.from_strava_api(raw)
                        if act.id in in_project_ids:
                            continue
                        act_ts = act.start_date.timestamp() if act.start_date else 0.0
                        if act_ts <= cutoff:
                            continue
                        act_date = act.start_date.date() if act.start_date else None
                        if act_date is None:
                            continue
                        if trip_start_date and act_date < trip_start_date:
                            continue
                        if trip_end_date and act_date > trip_end_date:
                            continue
                        d = act.to_strava_dict()
                        d["in_project"] = False
                        strava_results.append(d)
                    except Exception:
                        pass

        # ── Polarsteps ────────────────────────────────────────────────────────
        ps_results: List[Dict[str, Any]] = []
        ps_token = sess.exec(
            select(PolarstepsToken).where(PolarstepsToken.user_info_id == user_info_id)
        ).first()

        if ps_token and meta.linked_ps_trip_id:
            try:
                from datetime import datetime as _dt
                ps_client = PolarstepsClient(ps_token.remember_token)
                raw_steps = ps_client.get_trip_steps(meta.linked_ps_trip_id)
                cutoff = meta.last_ps_sync_at or 0.0
                for raw_step in raw_steps:
                    ct = raw_step.get("creation_time")
                    try:
                        step_ts = _dt.fromisoformat(ct).timestamp() if isinstance(ct, str) else float(ct or 0)
                    except (ValueError, TypeError):
                        step_ts = 0.0
                    if step_ts <= cutoff:
                        continue
                    ps_results.append(format_step(raw_step))
            except Exception:
                pass  # PS errors are non-fatal

    return {"strava": strava_results, "polarsteps": ps_results}


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a project")
def delete_project(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        found = _repo.delete_project(sess, user_info_id, name)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post("/import", status_code=status.HTTP_201_CREATED, response_model=ImportedOut,
             summary="Import a .viewtrip file")
async def import_project(
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    user_id = current_user["sub"]

    raw_fname = os.path.basename(file.filename or "imported.viewtrip")
    # Accept both .viewtrip (new) and .gettracks (legacy) on upload
    if raw_fname.endswith(ProjectIO.LEGACY_EXTENSION):
        fname = raw_fname[: -len(ProjectIO.LEGACY_EXTENSION)] + ProjectIO.EXTENSION
    elif raw_fname.endswith(ProjectIO.EXTENSION):
        fname = raw_fname
    else:
        fname = raw_fname + ProjectIO.EXTENSION

    # Write to a temp location so ingest_project can read it
    pdir = _projects_dir(user_id)
    tmp_path = os.path.join(pdir, fname)
    contents = await file.read()
    with open(tmp_path, "wb") as fh:
        fh.write(contents)

    name = fname[: -len(ProjectIO.EXTENSION)]
    with get_session() as sess:
        _repo.ingest_project(sess, user_info_id, tmp_path)

    return {"name": name, "filename": fname}


# ── GPX export ─────────────────────────────────────────────────────────────────

_SEGMENT_GPX_POINTS = 50
_SAFE_NAME = re.compile(r"[^\w\-. ]")


@router.get("/{name}/export", summary="Export project as GPX")
def export_project_gpx(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Build and stream the project as a GPX file."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    gpx = gpxpy.gpx.GPX()
    gpx.name = project.name
    gpx.creator = "ViewTripWeb"

    track = gpxpy.gpx.GPXTrack(name=project.name)
    gpx.tracks.append(track)

    for item in project.items:
        if item.item_type == "activity":
            act = project.activity_by_id(item.activity_id) if item.activity_id else None
            if act is None:
                continue

            seg = gpxpy.gpx.GPXTrackSegment()

            if act.summary_polyline:
                decoded = polyline_lib.decode(act.summary_polyline)
                for idx, (lat, lon) in enumerate(decoded):
                    pt = gpxpy.gpx.GPXTrackPoint(lat, lon)
                    if idx == 0 and act.start_date_local:
                        pt.time = act.start_date_local
                    seg.points.append(pt)
            elif act.start_latlng and act.end_latlng:
                pt_start = gpxpy.gpx.GPXTrackPoint(act.start_latlng[0], act.start_latlng[1])
                if act.start_date_local:
                    pt_start.time = act.start_date_local
                pt_end = gpxpy.gpx.GPXTrackPoint(act.end_latlng[0], act.end_latlng[1])
                seg.points.append(pt_start)
                seg.points.append(pt_end)
            else:
                continue

            if seg.points:
                track.segments.append(seg)

        elif item.item_type == "segment" and item.segment:
            cs = item.segment
            arc = great_circle_points(
                cs.start.lat, cs.start.lon,
                cs.end.lat,   cs.end.lon,
                n_points=_SEGMENT_GPX_POINTS,
            )
            seg = gpxpy.gpx.GPXTrackSegment()
            for lat, lon in arc:
                seg.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon))
            track.segments.append(seg)

        elif item.item_type == "memory" and item.memory:
            mem = item.memory
            if mem.lat is not None and mem.lon is not None:
                wpt = gpxpy.gpx.GPXWaypoint(mem.lat, mem.lon)
                wpt.name = mem.name or "Memory"
                wpt.description = mem.description
                if mem.date and mem.time:
                    try:
                        wpt.time = datetime.fromisoformat(f"{mem.date}T{mem.time}:00")
                    except ValueError:
                        pass
                gpx.waypoints.append(wpt)

    # Emit one <wpt> per day that has any day metadata
    if project.day_meta:
        # Build a map: date_key → first lat/lon from an activity on that day
        day_first_latlng: dict[str, tuple[float, float]] = {}
        for it in project.items:
            if it.item_type == "activity" and it.activity_id is not None:
                act = project.activity_by_id(it.activity_id)
                if act is None:
                    continue
                try:
                    date_key = act.start_date_local.date().isoformat()
                except AttributeError:
                    date_key = str(act.start_date_local)[:10]
                if date_key and date_key not in day_first_latlng and act.start_latlng:
                    day_first_latlng[date_key] = (act.start_latlng[0], act.start_latlng[1])

        for date_key, dm in project.day_meta.items():
            if not any([dm.difficulty, dm.sleeping, dm.weather, dm.journal]):
                continue
            lat, lon = day_first_latlng.get(date_key, (0.0, 0.0))
            wpt = gpxpy.gpx.GPXWaypoint(lat, lon)
            wpt.name = f"Day meta {date_key}"
            parts = [s for s in [
                dm.difficulty and f"Difficulty: {dm.difficulty}",
                dm.sleeping   and f"Sleeping: {dm.sleeping}",
                dm.weather    and f"Weather: {dm.weather}",
                dm.journal    and f"Journal: {dm.journal}",
            ] if s]
            wpt.description = " | ".join(parts)
            wpt.comment = json.dumps({
                "date": date_key,
                "difficulty": dm.difficulty,
                "sleeping": dm.sleeping,
                "weather": dm.weather,
                "journal": dm.journal,
            })
            gpx.waypoints.append(wpt)

    gpx_xml = gpx.to_xml()
    safe = _SAFE_NAME.sub("_", project.name)

    return StreamingResponse(
        io.BytesIO(gpx_xml.encode("utf-8")),
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{safe}.gpx"'},
    )


# ── .viewtrip export ──────────────────────────────────────────────────────────

@router.get("/{name}/export-viewtrip", summary="Export project as .viewtrip file")
def export_project_viewtrip(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Download the project as a .viewtrip JSON file (no embedded photos)."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    data: Dict[str, Any] = ProjectIO.to_dict(project)
    # Override activities with the raw Strava format (no elevation_profile pairs) for the backup file
    data["activities"] = [a.to_strava_dict() for a in project.activities]
    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    safe = _SAFE_NAME.sub("_", project.name)
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe}.viewtrip"'},
    )


# ── ZIP export (.viewtrip + photos) ───────────────────────────────────────────

@router.get("/{name}/export-zip", summary="Export project as ZIP (with photos)")
def export_project_zip(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Download a ZIP containing the .viewtrip file and all memory photos."""
    user_info_id = int(current_user["sub"])
    user_id = current_user["sub"]
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(user_id, name),
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    # Serialise items, adding relative photo_refs for memories.
    items_serialised = []
    for item in project.items:
        d = ProjectIO._serialise_item(item)
        if item.item_type == "memory" and item.memory and item.memory.id and item.memory.photos:
            d["memory"]["photo_refs"] = [
                f"photos/{item.memory.id}/{uuid}.jpg"
                for uuid in item.memory.photos
            ]
        items_serialised.append(d)

    data: Dict[str, Any] = {
        "version": project.version,
        "name": project.name,
        "trip_start": project.trip_start,
        "filter_state": {
            "start_date": project.filter_state.start_date,
            "end_date": project.filter_state.end_date,
            "activity_types": project.filter_state.activity_types,
        },
        "items": items_serialised,
        "activities": [a.to_strava_dict() for a in project.activities],
    }
    viewtrip_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

    zip_buffer = io.BytesIO()
    safe = _SAFE_NAME.sub("_", project.name)
    memories_base = Path(_DATA_DIR) / "users" / user_id / "memories"
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{safe}.viewtrip", viewtrip_bytes)
        for item in project.items:
            if item.item_type != "memory" or item.memory is None or item.memory.id is None:
                continue
            mem = item.memory
            mem_dir = memories_base / str(mem.id)
            for photo_uuid in mem.photos:
                full_path = mem_dir / f"{photo_uuid}.jpg"
                if full_path.exists():
                    zf.write(full_path, f"photos/{mem.id}/{photo_uuid}.jpg")

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{safe}.zip"'},
    )


# ── Activity management ────────────────────────────────────────────────────────

class AddActivitiesRequest(BaseModel):
    activities: List[Dict[str, Any]]


@router.post("/{name}/activities", response_model=ActivitiesAddedOut,
             summary="Add activities to project")
def add_activities(
    name: str,
    body: AddActivitiesRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    """Add activities to a project, enriching GPS streams from Strava.

    If the rate limit is approached, remaining activities are queued for
    enrichment after the 15-min window resets.
    """
    user_info_id = int(current_user["sub"])

    activities: List[Activity] = []
    for raw in body.activities:
        try:
            activities.append(Activity.from_strava_api(raw))
        except Exception:
            pass

    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        added = project.add_activities(activities)
        _repo.save_project(sess, user_info_id, project)

    bust_geo_cache(user_info_id, name)

    # Enrich GPS streams in the background immediately — never blocks this response.
    activity_ids = [a.id for a in activities if a.id is not None]
    if activity_ids:
        background_tasks.add_task(
            _enrich_activities_background, activity_ids, user_info_id, name
        )

    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)

    return {
        "added": added,
        "total": len(project.activities),
        "pending_enrichment": len(activity_ids),
    }


# ── Single-activity refresh ────────────────────────────────────────────────────

@router.post("/{name}/activities/{activity_id}/refresh", summary="Refresh activity from Strava")
def refresh_activity(
    name: str,
    activity_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Re-fetch a single activity from Strava and update the stored data.

    Fetches fresh metadata (name, distance, kudos, etc.) plus full GPS streams
    (polyline + elevation).  Useful when the user has edited the activity on
    Strava and wants the local copy to reflect those changes.

    Returns the updated activity dict (same shape as the activities list in
    GET /api/projects/{name}).
    """
    user_info_id = int(current_user["sub"])

    # Locally edited tracks must never be overwritten by a Strava re-fetch.
    # Surface a clear message so the client can prompt the user to reset first.
    if _repo.activity_is_edited(activity_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This activity has a locally edited track. "
                   "Reset it to Strava before refreshing.",
        )

    client = _strava_client_for_user(user_info_id)
    if client is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Strava not connected",
        )

    # 1. Fetch fresh activity metadata from Strava
    try:
        raw = client.get_activity(activity_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Strava fetch failed: {exc}",
        )

    act = Activity.from_strava_api(raw)

    # 2. Enrich with full GPS streams (single call — check rate limit first)
    if client.remaining_requests > 2:
        try:
            streams  = client.get_activity_streams(activity_id)
            latlng   = streams.get("latlng",   {}).get("data") or []
            altitude = streams.get("altitude", {}).get("data") or []
            distance = streams.get("distance", {}).get("data") or []
            if latlng:
                act.summary_polyline = polyline_lib.encode(
                    [(pt[0], pt[1]) for pt in latlng]
                )
                # Derive start/end from stream if metadata didn't provide them
                if not act.start_latlng:
                    act.start_latlng = [latlng[0][0], latlng[0][1]]
                if not act.end_latlng:
                    act.end_latlng = [latlng[-1][0], latlng[-1][1]]
            n = min(len(altitude), len(distance))
            if n >= 2:
                act.elevation_profile = (
                    [distance[i] / 1000 for i in range(n)],
                    [altitude[i]        for i in range(n)],
                )
        except Exception:
            pass  # streams failed — still save the refreshed metadata

    # 3. Overwrite the DB row (all columns, including enrichment)
    with get_session() as sess:
        _repo.force_update_activity(sess, user_info_id, act)
        bust_geo_cache(user_info_id, name)
        # Return the updated project so the client can refresh its state
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return _repo.to_dict(project)


# ── Activity geometry editing (issue #31) ─────────────────────────────────────

class TrackPointIn(BaseModel):
    lat: float
    lng: float
    elev: Optional[float] = None


class TrackEditRequest(BaseModel):
    points: List[TrackPointIn] = Field(
        description="Full edited track as an ordered list of {lat, lng, elev?} points")


def _project_contains_activity(project, activity_id: int) -> bool:
    return any(
        it.item_type == "activity" and it.activity_id == activity_id
        for it in project.items
    )


@router.get("/{name}/activities/{activity_id}/track",
            summary="Get a single activity's editable geometry")
def get_activity_track(
    name: str,
    activity_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return one activity's editor payload (map.summary_polyline + elevation_profile
    pairs), so the track editor doesn't download the whole project just to edit a
    single activity — the full GET /{name} payload is 10-15x larger. Same per-activity
    shape as GET /{name}.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    activity = next((a for a in project.activities if a.id == activity_id), None)
    if activity is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not in project")
    d = activity.to_strava_dict()
    ep = activity.elevation_profile or getattr(activity, "elevation_profile_low_res", None)
    d["elevation_profile"] = [list(pair) for pair in zip(ep[0], ep[1])] if ep else None
    return d


@router.put("/{name}/activities/{activity_id}/track",
            summary="Replace an activity's track geometry")
def edit_activity_track(
    name: str,
    activity_id: int,
    body: TrackEditRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    """Overwrite an activity's track with an edited point list (trim/add/remove).

    Snapshots the original geometry on the first edit, marks the activity edited
    (so Strava sync skips it), recomputes distance / elevation / times, and
    returns the updated project.
    """
    from src.models.track_edit import TrackPoint

    user_info_id = int(current_user["sub"])
    if len(body.points) < 2:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A track needs at least 2 points",
        )
    points = [TrackPoint(lat=p.lat, lng=p.lng, elev=p.elev) for p in body.points]

    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if not _project_contains_activity(project, activity_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not in project")
        if not _repo.edit_activity_track(sess, activity_id, points):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )

    bust_geo_cache(user_info_id, name)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)
    return _repo.to_dict(project)


@router.post("/{name}/activities/{activity_id}/reset",
             summary="Reset an edited activity's track to the original")
def reset_activity_track(
    name: str,
    activity_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    """Restore an edited activity's geometry from its snapshot and clear is_edited."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if not _project_contains_activity(project, activity_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not in project")
        if not _repo.reset_activity_track(sess, activity_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Activity has no edit to reset",
            )
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )

    bust_geo_cache(user_info_id, name)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)
    return _repo.to_dict(project)


class SplitRequest(BaseModel):
    split_index: int = Field(
        description="0-based point index at which to split; the point is shared "
                    "as the last point of the head and the first of the tail")


@router.post("/{name}/activities/{activity_id}/split",
             summary="Split an activity into a head and a local tail")
def split_activity(
    name: str,
    activity_id: int,
    body: SplitRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    """Split an activity at *split_index*: the head keeps its Strava id, the tail
    becomes a new LOCAL activity (negative id, manual, "<name> (2)") inserted
    right after the head. Both pieces are marked edited. Returns the updated project.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_project_row(sess, user_info_id, name)
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None or not _project_contains_activity(project, activity_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not in project")
        try:
            tail_id = _repo.split_activity(
                sess, user_info_id, row.id, activity_id, body.split_index)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
        if tail_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Activity not found")
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )

    bust_geo_cache(user_info_id, name)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)
    return _repo.to_dict(project)


@router.delete("/{name}/activities/{activity_id}/local",
               status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a local (split-tail) activity")
def delete_local_activity(
    name: str,
    activity_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    """Delete a local (negative-id) activity row and unlink it from the project.

    Only local activities may be deleted (Strava activities are shared). This is
    the undo path for a split — deleting the tail leaves the head in place.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = _get_project_row(sess, user_info_id, name)
        if not _repo.delete_local_activity(sess, row.id, activity_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Local activity not found",
            )
    bust_geo_cache(user_info_id, name)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)


# ── Item management (delete + reorder) ────────────────────────────────────────

@router.delete("/{name}/items/{index}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Remove an item from the project")
def delete_item(
    name: str,
    index: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if index < 0 or index >= len(project.items):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Index out of range")
        removed = project.items[index]
        project.remove_item(index)
        _repo.save_project(sess, user_info_id, project)
        # A split tail is a LOCAL (negative-id) activity owned solely by its
        # timeline item. remove_item only unlinks the item, so without this the
        # row is orphaned in the activity table and its negative id gets reused
        # by the next split -> UNIQUE constraint failure. Delete the row once no
        # remaining item references it.
        if (
            removed.item_type == "activity"
            and (removed.activity_id or 0) < 0
            and not any(
                it.item_type == "activity" and it.activity_id == removed.activity_id
                for it in project.items
            )
        ):
            row = _get_project_row(sess, user_info_id, name)
            _repo.delete_local_activity(sess, row.id, removed.activity_id)
    bust_geo_cache(user_info_id, name)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)


class ReorderRequest(BaseModel):
    from_index: int
    to_index: int


@router.put("/{name}/items/reorder", summary="Reorder project items")
def reorder_items(
    name: str,
    body: ReorderRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        project.move_item(body.from_index, body.to_index)
        _repo.save_project(sess, user_info_id, project)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)
    return [ProjectIO._serialise_item(i) for i in project.items]


@router.put("/{name}/items/sort", status_code=status.HTTP_204_NO_CONTENT,
            summary="Sort project items chronologically")
def sort_items(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
) -> None:
    """Re-order all project items by date/time.

    Sort keys by item type:
    - activity  → start_date_local
    - memory    → date + time
    - journal   → date + time
    - segment   → date field if set; otherwise inherits the date of the
                  preceding dated item so undated segments stay near the
                  activities they connect.
    Items with no resolvable date are placed at the end, preserving their
    relative order (stable sort).
    """
    FALLBACK = "9999-12-31T23:59:59"

    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        # Build a lookup: (lat_4dp, lon_4dp) → activity start_date isoformat
        # for every activity end-point. Segments whose start coordinates match
        # an activity's end coordinates are sorted immediately after that activity,
        # regardless of where they currently sit in the list.
        act_end_to_date: Dict[tuple, str] = {}
        for item in project.items:
            if item.item_type == "activity" and item.activity_id is not None:
                act = project._activity_map.get(item.activity_id)
                if act and act.end_latlng and act.start_date:
                    k = (round(act.end_latlng[0], 4), round(act.end_latlng[1], 4))
                    act_end_to_date[k] = act.start_date.isoformat()

        # First pass: assign each item a sort key.
        keys: List[str] = []
        last_date = FALLBACK
        for item in project.items:
            key: str = FALLBACK
            if item.item_type == "activity" and item.activity_id is not None:
                act = project._activity_map.get(item.activity_id)
                if act and act.start_date:
                    key = act.start_date.isoformat()
            elif item.item_type == "memory" and item.memory is not None:
                d = item.memory.date
                t = item.memory.time or "00:00"
                if d:
                    key = f"{d}T{t}"
            elif item.item_type == "journal" and item.journal is not None:
                d = item.journal.date
                t = getattr(item.journal, "time", None) or "00:00"
                if d:
                    key = f"{d}T{t}"
            elif item.item_type == "encounter" and item.encounter is not None:
                d = item.encounter.date
                t = getattr(item.encounter, "time", None) or "00:00"
                if d:
                    key = f"{d}T{t}"
            elif item.item_type == "segment" and item.segment is not None:
                seg = item.segment
                # Primary: match segment start → activity end by coordinates.
                if seg.start:
                    coord_key = (round(seg.start.lat, 4), round(seg.start.lon, 4))
                    matched = act_end_to_date.get(coord_key)
                    if matched:
                        key = matched  # sort right after the departing activity
                # Fallback: use date field or inherit from predecessor.
                if key == FALLBACK:
                    if seg.date:
                        pred_day = last_date[:10] if last_date != FALLBACK else None
                        key = last_date if pred_day == seg.date else f"{seg.date}T00:00:01"
                    else:
                        key = last_date

            if key != FALLBACK:
                last_date = key
            keys.append(key)

        # Stable sort: items with the same key preserve their original order.
        project.items = [
            item for _, item in sorted(
                zip(keys, project.items), key=lambda t: t[0]
            )
        ]
        _repo.save_project(sess, user_info_id, project)
    bust_geo_cache(user_info_id, name)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)


# ── Segment CRUD ───────────────────────────────────────────────────────────────

class SegmentBody(BaseModel):
    segment_type: str = "flight"
    label: str = ""
    start_lat: float = 0.0
    start_lon: float = 0.0
    end_lat: float = 0.0
    end_lon: float = 0.0
    insert_after_index: Optional[int] = None  # POST only
    date: Optional[str] = None  # ISO date "YYYY-MM-DD"
    train_number: Optional[str] = None
    hafas_provider: Optional[str] = None
    route_mode: Optional[str] = None  # "great_circle" | "rail"; None = preserve


@router.post("/{name}/segments", status_code=status.HTTP_201_CREATED,
             response_model=SegmentIDOut, summary="Add a transport segment")
def create_segment(
    name: str,
    body: SegmentBody,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    user_info_id = int(current_user["sub"])
    seg = ConnectingSegment(
        id=str(uuid.uuid4()),
        segment_type=body.segment_type,
        label=body.label,
        date=body.date,
        start=SegmentEndpoint(lat=body.start_lat, lon=body.start_lon),
        end=SegmentEndpoint(lat=body.end_lat, lon=body.end_lon),
        train_number=body.train_number,
        hafas_provider=body.hafas_provider,
    )
    item = ProjectItem(item_type="segment", segment=seg)

    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        insert_at = len(project.items)
        if body.insert_after_index is not None:
            insert_at = max(0, min(len(project.items), body.insert_after_index + 1))
        project.items.insert(insert_at, item)
        _repo.save_project(sess, user_info_id, project, check_version=True)
    bust_geo_cache(user_info_id, name)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)
    return {"id": seg.id}


@router.put("/{name}/segments/{seg_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Update a transport segment")
def update_segment(
    name: str,
    seg_id: str,
    body: SegmentBody,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        for item in project.items:
            if item.item_type == "segment" and item.segment and item.segment.id == seg_id:
                seg = item.segment
                coords_changed = (
                    seg.start.lat != body.start_lat or seg.start.lon != body.start_lon or
                    seg.end.lat != body.end_lat     or seg.end.lon != body.end_lon
                )
                seg.segment_type  = body.segment_type
                seg.label         = body.label
                seg.date          = body.date
                seg.start         = SegmentEndpoint(lat=body.start_lat, lon=body.start_lon)
                seg.end           = SegmentEndpoint(lat=body.end_lat,   lon=body.end_lon)
                seg.train_number  = body.train_number
                seg.hafas_provider = body.hafas_provider
                if coords_changed or body.route_mode == "great_circle":
                    seg.route_mode     = "great_circle"
                    seg.route_polyline = None
                elif body.route_mode == "rail":
                    seg.route_mode = "rail"
                _repo.save_project(sess, user_info_id, project, check_version=True)
                bust_geo_cache(user_info_id, name)
                background_tasks.add_task(_refresh_stats_background, user_info_id, name)
                background_tasks.add_task(_refresh_share_tiles, user_info_id, name)
                return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")


@router.delete("/{name}/segments/{seg_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a transport segment")
def delete_segment(
    name: str,
    seg_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        original_len = len(project.items)
        project.items = [
            i for i in project.items
            if not (i.item_type == "segment" and i.segment and i.segment.id == seg_id)
        ]
        if len(project.items) == original_len:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
        _repo.save_project(sess, user_info_id, project, check_version=True)
    bust_geo_cache(user_info_id, name)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    background_tasks.add_task(_refresh_share_tiles, user_info_id, name)


# ── Project sharing ────────────────────────────────────────────────────────────

@router.post("/{name}/share", response_model=ShareTokenOut, summary="Create share link")
def create_share_link(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Generate (or return existing) share token for public read-only access."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if not row.share_token:
            row.share_token = str(uuid.uuid4())
            sess.add(row)
            sess.commit()
        token = row.share_token
    return {"share_token": token}


class ResolveRouteRequest(BaseModel):
    hafas_provider: Optional[str] = None   # omit to skip HAFAS
    train_number: Optional[str] = None
    date: Optional[str] = None             # ISO "YYYY-MM-DD"; defaults to segment.date


@router.post("/{name}/segments/{seg_id}/resolve-route", response_model=RouteResolveTriggered,
             status_code=status.HTTP_202_ACCEPTED,
             summary="Trigger async route resolution for a train, ferry, or bus segment")
def resolve_segment_route(
    name: str,
    seg_id: str,
    body: ResolveRouteRequest,
    background_tasks: BackgroundTasks,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """
    Schedule OSM-based route resolution for a train, boat, or bus segment.

    Resolution (HAFAS stop sequence + Overpass track geometry) can take tens of
    seconds, so it runs as a background task rather than blocking the request —
    this is what previously caused proxy 504s on long routes.

    The segment is marked ``route_status="pending"`` synchronously and a 202 is
    returned immediately.  The client polls ``/meta`` until the segment flips to
    ``resolved`` or ``failed``.  See :func:`_resolve_route_job`.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

        seg = next(
            (i.segment for i in project.items
             if i.item_type == "segment" and i.segment and i.segment.id == seg_id),
            None,
        )
        if seg is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
        if seg.segment_type not in ("train", "boat", "bus"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Route resolution only supported for train, boat, and bus segments",
            )

        seg.route_status = "pending"
        seg.route_error = None
        seg.route_degraded = False
        seg.route_started_at = datetime.now(timezone.utc).isoformat()
        if body.train_number:
            seg.train_number = body.train_number
        if body.hafas_provider:
            seg.hafas_provider = body.hafas_provider
        _repo.save_project(sess, user_info_id, project, check_version=True)
    bust_geo_cache(user_info_id, name)

    background_tasks.add_task(
        _resolve_route_job, user_info_id, name, seg_id, body.model_dump()
    )
    return {"status": "pending", "route_status": "pending"}


@router.delete("/{name}/share", status_code=status.HTTP_204_NO_CONTENT)
def revoke_share_link(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Revoke the share token — the project becomes private again."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if row.share_token:
            from src.tile_renderer import invalidate_tile_cache
            from api.share import invalidate_share_cache
            invalidate_tile_cache(row.share_token)
            invalidate_share_cache(row.share_token)
        row.share_token = None
        sess.add(row)
        sess.commit()


@router.get("/{name}/share-info", response_model=ShareInfoOut, summary="Get share tokens")
def get_share_info(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return both share tokens for the project (null when not yet created)."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        return {
            "share_token": row.share_token,
            "share_token_no_memories": row.share_token_no_memories,
        }


@router.post("/{name}/share/no-memories", response_model=ShareTokenNoMemoriesOut,
             summary="Create no-memories share link")
def create_share_link_no_memories(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create (idempotent) a share token that strips memory items."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if not row.share_token_no_memories:
            row.share_token_no_memories = str(uuid.uuid4())
            sess.add(row)
            sess.commit()
        return {"share_token_no_memories": row.share_token_no_memories}


@router.delete("/{name}/share/no-memories", status_code=status.HTTP_204_NO_CONTENT,
               summary="Revoke no-memories share link")
def revoke_share_link_no_memories(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Revoke the no-memories share token."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        if row.share_token_no_memories:
            from src.tile_renderer import invalidate_tile_cache
            from api.share import invalidate_share_cache
            invalidate_tile_cache(row.share_token_no_memories)
            invalidate_share_cache(row.share_token_no_memories)
        row.share_token_no_memories = None
        sess.add(row)
        sess.commit()


@router.get("/{name}/share/visitors", summary="Get share link visitor stats")
def get_share_visitors(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return visitor stats for both share link types.

    Response shape:
      {
        full: { anonymous_count: N, registered: [{display_name, email, last_seen_at}] },
        no_memories: { anonymous_count: N, registered: [...] }
      }
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(
                DBProject.user_info_id == user_info_id,
                DBProject.name == name,
            )
        ).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        project_id = row.id

        visits = sess.exec(
            select(DBShareVisit).where(DBShareVisit.project_id == project_id)
        ).all()

    result: Dict[str, Any] = {
        "full": {"anonymous_count": 0, "registered": []},
        "no_memories": {"anonymous_count": 0, "registered": []},
    }

    registered_ids: Dict[str, List[int]] = {"full": [], "no_memories": []}
    last_seen: Dict[str, Dict[int, float]] = {"full": {}, "no_memories": {}}

    for v in visits:
        bucket = v.token_type if v.token_type in result else "full"
        if v.visitor_type == "anonymous":
            result[bucket]["anonymous_count"] += 1
        else:
            if v.user_info_id is not None:
                registered_ids[bucket].append(v.user_info_id)
                last_seen[bucket][v.user_info_id] = v.last_seen_at

    with get_session() as sess:
        for bucket in ("full", "no_memories"):
            ids = registered_ids[bucket]
            if not ids:
                continue
            users = sess.exec(
                select(UserInfo).where(UserInfo.id.in_(ids))
            ).all()
            result[bucket]["registered"] = [
                {
                    "display_name": u.display_name,
                    "email": u.email,
                    "last_seen_at": last_seen[bucket].get(u.id, 0.0),
                }
                for u in users
            ]

    return result
