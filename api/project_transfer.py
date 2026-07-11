"""REST project import/export endpoints — .viewtrip upload, GPX/.viewtrip/ZIP download.

Routes:
    POST   /api/projects/import                 — upload a .viewtrip file
    GET    /api/projects/{name}/export          — download project as GPX file
    GET    /api/projects/{name}/export-viewtrip — download project as .viewtrip JSON
    GET    /api/projects/{name}/export-zip      — download ZIP (.viewtrip + photos)
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any, Dict

import gpxpy
import gpxpy.gpx
import polyline as polyline_lib
from models.db import get_session

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.project_shared import _DATA_DIR, _legacy_path, _projects_dir, _repo
from src.models.great_circle import great_circle_points
from src.project.project_io import ProjectIO

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ── Response schemas ──────────────────────────────────────────────────────────

class ImportedOut(BaseModel):
    name: str = Field(description="Name of the imported project")


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
