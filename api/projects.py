"""REST projects endpoints — list, create, open, delete, and manage projects.

Routes:
    GET    /api/projects/                       — list saved projects for current user
    POST   /api/projects/                       — create new project
    GET    /api/projects/{name}                 — get project data (GeoJSON + metadata)
    DELETE /api/projects/{name}                 — delete a project
    POST   /api/projects/import                 — upload a .gettracks file
    GET    /api/projects/{name}/export          — download project as GPX file
    GET    /api/projects/{name}/export-gettracks — download project as .gettracks JSON
    GET    /api/projects/{name}/export-zip      — download ZIP (gettracks + photos)
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
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

import gpxpy
import gpxpy.gpx
import polyline as polyline_lib
from models.db import get_session
from sqlmodel import select

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_current_user
from models.project_db import DBProject
from models.user import StravaToken
from src.api.strava_client import RateLimiter, StravaAPI
from src.config.settings import Config
from src.models.activity import Activity
from src.models.great_circle import great_circle_points
from src.models.project import ConnectingSegment, ProjectItem, SegmentEndpoint
from src.project.project_io import ProjectIO
from src.project.project_repo import ProjectRepo

_cfg = Config("config/config.json")
if os.environ.get("STRAVA_CLIENT_ID"):
    _cfg.set("strava.client_id", os.environ["STRAVA_CLIENT_ID"])
if os.environ.get("STRAVA_CLIENT_SECRET"):
    _cfg.set("strava.client_secret", os.environ["STRAVA_CLIENT_SECRET"])
_repo = ProjectRepo()

router = APIRouter(prefix="/api/projects", tags=["projects"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


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


def _enrich_pending_background(
    pending_ids: List[int],
    user_info_id: int,
    project_name: str,
) -> None:
    """Sleep until the Strava rate-limit window resets, then enrich remaining activities."""
    time.sleep(RateLimiter.WINDOW_SECONDS + 5)

    client = _strava_client_for_user(user_info_id)
    if client is None:
        return

    for activity_id in pending_ids:
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
        except Exception:
            pass


def _refresh_stats_background(user_info_id: int, project_name: str) -> None:
    """Background task: open a fresh session and recompute project stats."""
    with get_session() as sess:
        _repo.compute_and_cache_stats(sess, user_info_id, project_name)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def list_projects(current_user: Annotated[dict, Depends(get_current_user)]):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        return _repo.list_projects(sess, user_info_id)


class CreateProjectRequest(BaseModel):
    name: str


@router.post("/", status_code=status.HTTP_201_CREATED)
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


@router.get("/{name}")
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


@router.get("/{name}/stats")
def get_project_stats(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return pre-computed project statistics (computed on-the-fly if not cached yet)."""
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
        if row.stats_json is None:
            # First-time access: compute synchronously, then return
            _repo.compute_and_cache_stats(sess, user_info_id, name)
            row = sess.exec(
                select(DBProject).where(
                    DBProject.user_info_id == user_info_id,
                    DBProject.name == name,
                )
            ).first()
        stats = json.loads(row.stats_json or "{}")
    return stats


class ProjectUpdateRequest(BaseModel):
    new_name: Optional[str] = None
    trip_start: Optional[str] = None  # "YYYY-MM-DD" or None to clear


@router.put("/{name}")
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

        sess.add(row)
        sess.commit()
        result_name = row.name
        result_trip_start = row.trip_start
    return {"name": result_name, "trip_start": result_trip_start}


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        found = _repo.delete_project(sess, user_info_id, name)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_project(
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_info_id = int(current_user["sub"])
    user_id = current_user["sub"]

    fname = os.path.basename(file.filename or "imported.gettracks")
    if not fname.endswith(ProjectIO.EXTENSION):
        fname += ProjectIO.EXTENSION

    # Write to a temp location so ingest_gettracks can read it
    pdir = _projects_dir(user_id)
    tmp_path = os.path.join(pdir, fname)
    contents = await file.read()
    with open(tmp_path, "wb") as fh:
        fh.write(contents)

    name = fname[: -len(ProjectIO.EXTENSION)]
    with get_session() as sess:
        _repo.ingest_gettracks(sess, user_info_id, tmp_path)

    return {"name": name, "filename": fname}


# ── GPX export ─────────────────────────────────────────────────────────────────

_SEGMENT_GPX_POINTS = 50
_SAFE_NAME = re.compile(r"[^\w\-. ]")


@router.get("/{name}/export")
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

    gpx_xml = gpx.to_xml()
    safe = _SAFE_NAME.sub("_", project.name)

    return StreamingResponse(
        io.BytesIO(gpx_xml.encode("utf-8")),
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{safe}.gpx"'},
    )


# ── .gettracks export ─────────────────────────────────────────────────────────

@router.get("/{name}/export-gettracks")
def export_project_gettracks(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Download the project as a .gettracks JSON file (no embedded photos)."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    data: Dict[str, Any] = {
        "version": project.version,
        "name": project.name,
        "trip_start": project.trip_start,
        "filter_state": {
            "start_date": project.filter_state.start_date,
            "end_date": project.filter_state.end_date,
            "activity_types": project.filter_state.activity_types,
        },
        "items": [ProjectIO._serialise_item(i) for i in project.items],
        "activities": [a.to_strava_dict() for a in project.activities],
    }
    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    safe = _SAFE_NAME.sub("_", project.name)
    return StreamingResponse(
        io.BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe}.gettracks"'},
    )


# ── ZIP export (gettracks + photos) ───────────────────────────────────────────

@router.get("/{name}/export-zip")
def export_project_zip(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Download a ZIP containing the .gettracks file and all memory photos."""
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
    gettracks_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

    zip_buffer = io.BytesIO()
    safe = _SAFE_NAME.sub("_", project.name)
    memories_base = Path(_DATA_DIR) / "users" / user_id / "memories"
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{safe}.gettracks", gettracks_bytes)
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


@router.post("/{name}/activities")
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

    pending: List[Activity] = []
    client = _strava_client_for_user(user_info_id)
    if client is not None:
        pending = _enrich_activities(activities, client)

    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        added = project.add_activities(activities)
        _repo.save_project(sess, user_info_id, project)

    if pending:
        pending_ids = [a.id for a in pending if a.id is not None]
        background_tasks.add_task(
            _enrich_pending_background, pending_ids, user_info_id, name
        )

    background_tasks.add_task(_refresh_stats_background, user_info_id, name)

    return {
        "added": added,
        "total": len(project.activities),
        "pending_enrichment": len(pending),
    }


# ── Single-activity refresh ────────────────────────────────────────────────────

@router.post("/{name}/activities/{activity_id}/refresh")
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
        # Return the updated project so the client can refresh its state
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )

    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    return _repo.to_dict(project)


# ── Item management (delete + reorder) ────────────────────────────────────────

@router.delete("/{name}/items/{index}", status_code=status.HTTP_204_NO_CONTENT)
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
        project.remove_item(index)
        _repo.save_project(sess, user_info_id, project)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)


class ReorderRequest(BaseModel):
    from_index: int
    to_index: int


@router.put("/{name}/items/reorder")
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
    return [ProjectIO._serialise_item(i) for i in project.items]


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


@router.post("/{name}/segments", status_code=status.HTTP_201_CREATED)
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
        _repo.save_project(sess, user_info_id, project)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)
    return {"id": seg.id}


@router.put("/{name}/segments/{seg_id}", status_code=status.HTTP_204_NO_CONTENT)
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
                item.segment.segment_type = body.segment_type
                item.segment.label = body.label
                item.segment.date = body.date
                item.segment.start = SegmentEndpoint(lat=body.start_lat, lon=body.start_lon)
                item.segment.end = SegmentEndpoint(lat=body.end_lat, lon=body.end_lon)
                _repo.save_project(sess, user_info_id, project)
                background_tasks.add_task(_refresh_stats_background, user_info_id, name)
                return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")


@router.delete("/{name}/segments/{seg_id}", status_code=status.HTTP_204_NO_CONTENT)
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
        _repo.save_project(sess, user_info_id, project)
    background_tasks.add_task(_refresh_stats_background, user_info_id, name)


# ── Project sharing ────────────────────────────────────────────────────────────

@router.post("/{name}/share")
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
        row.share_token = None
        sess.add(row)
        sess.commit()
