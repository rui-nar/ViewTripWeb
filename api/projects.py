"""REST projects endpoints — list, create, open, delete, and manage projects.

Routes:
    GET    /api/projects/                       — list saved projects for current user
    POST   /api/projects/                       — create new project
    GET    /api/projects/{name}                 — get project data (GeoJSON + metadata)
    DELETE /api/projects/{name}                 — delete a project
    POST   /api/projects/import                 — upload a .gettracks file
    GET    /api/projects/{name}/export          — download project as GPX file
    POST   /api/projects/{name}/activities      — add activities to project
    DELETE /api/projects/{name}/items/{index}   — remove item at index
    PUT    /api/projects/{name}/items/reorder   — move item from/to index
    POST   /api/projects/{name}/segments        — create a connecting segment
    PUT    /api/projects/{name}/segments/{id}   — update a segment
    DELETE /api/projects/{name}/segments/{id}   — delete a segment
"""
from __future__ import annotations

import io
import os
import re
import uuid
from typing import Annotated, Any, Dict, List, Optional

import gpxpy
import gpxpy.gpx
import polyline as polyline_lib

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.deps import get_current_user
from src.models.activity import Activity
from src.models.great_circle import great_circle_points
from src.models.project import ConnectingSegment, ProjectItem, SegmentEndpoint
from src.project.project_io import ProjectIO

router = APIRouter(prefix="/api/projects", tags=["projects"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


def _projects_dir(user_id: str) -> str:
    path = os.path.join(_DATA_DIR, "users", user_id, "projects")
    os.makedirs(path, exist_ok=True)
    return path


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def list_projects(current_user: Annotated[dict, Depends(get_current_user)]):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    projects = []
    for fname in sorted(os.listdir(pdir)):
        if fname.endswith(ProjectIO.EXTENSION):
            projects.append({
                "name": fname[: -len(ProjectIO.EXTENSION)],
                "filename": fname,
            })
    return projects


class CreateProjectRequest(BaseModel):
    name: str


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_project(
    body: CreateProjectRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    name = body.name.strip() or "My Trip"
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if os.path.exists(path):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project '{name}' already exists",
        )
    project = ProjectIO.new(name)
    ProjectIO.save(project, path)
    return {"name": name, "filename": name + ProjectIO.EXTENSION}


@router.get("/{name}")
def get_project(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    project = ProjectIO.load(path)
    return ProjectIO.to_dict(project)


@router.delete("/{name}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    os.remove(path)


@router.post("/import", status_code=status.HTTP_201_CREATED)
async def import_project(
    file: Annotated[UploadFile, File()],
    current_user: Annotated[dict, Depends(get_current_user)],
):
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    fname = os.path.basename(file.filename or "imported.gettracks")
    if not fname.endswith(ProjectIO.EXTENSION):
        fname += ProjectIO.EXTENSION
    dest = os.path.join(pdir, fname)
    contents = await file.read()
    with open(dest, "wb") as fh:
        fh.write(contents)
    return {"name": fname[: -len(ProjectIO.EXTENSION)], "filename": fname}


# ── GPX export ─────────────────────────────────────────────────────────────────

# How many great-circle points to interpolate per connecting segment.
_SEGMENT_GPX_POINTS = 50

# Safe filename characters
_SAFE_NAME = re.compile(r"[^\w\-. ]")


@router.get("/{name}/export")
def export_project_gpx(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Build and stream the project as a GPX file.

    Each project item (activity or connecting segment) becomes one <trkseg>
    inside a single <trk>.  The caller receives a GPX attachment.

    Track points are derived from:
    - Activities: decoded from ``summary_polyline`` (Google encoded polyline)
      with ``start_date_local`` as the timestamp of the first point.
      Falls back to a two-point segment using start_latlng / end_latlng.
    - Connecting segments: SLERP great-circle arc (50 points).
    """
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    project = ProjectIO.load(path)

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
                decoded = polyline_lib.decode(act.summary_polyline)  # [(lat, lon), ...]
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
                continue  # no GPS data at all — skip

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

    gpx_xml = gpx.to_xml()
    safe = _SAFE_NAME.sub("_", project.name)
    filename = f"{safe}.gpx"

    return StreamingResponse(
        io.BytesIO(gpx_xml.encode("utf-8")),
        media_type="application/gpx+xml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Activity management ────────────────────────────────────────────────────────

class AddActivitiesRequest(BaseModel):
    activities: List[Dict[str, Any]]


@router.post("/{name}/activities")
def add_activities(
    name: str,
    body: AddActivitiesRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Add specific activities (by strava dict list) to a project."""
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    activities: List[Activity] = []
    for raw in body.activities:
        try:
            activities.append(Activity.from_strava_api(raw))
        except Exception:
            pass

    project = ProjectIO.load(path)
    added = project.add_activities(activities)
    ProjectIO.save(project, path)
    return {"added": added, "total": len(project.activities)}


# ── Item management (delete + reorder) ────────────────────────────────────────

@router.delete("/{name}/items/{index}", status_code=status.HTTP_204_NO_CONTENT)
def delete_item(
    name: str,
    index: int,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Remove the item at *index* from the project's ordered list."""
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    project = ProjectIO.load(path)
    if index < 0 or index >= len(project.items):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Index out of range")
    project.remove_item(index)
    ProjectIO.save(project, path)


class ReorderRequest(BaseModel):
    from_index: int
    to_index: int


@router.put("/{name}/items/reorder")
def reorder_items(
    name: str,
    body: ReorderRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Move item from *from_index* to *to_index*."""
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    project = ProjectIO.load(path)
    project.move_item(body.from_index, body.to_index)
    ProjectIO.save(project, path)
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


@router.post("/{name}/segments", status_code=status.HTTP_201_CREATED)
def create_segment(
    name: str,
    body: SegmentBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Create a new connecting segment and insert it into the project."""
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    seg = ConnectingSegment(
        id=str(uuid.uuid4()),
        segment_type=body.segment_type,
        label=body.label,
        start=SegmentEndpoint(lat=body.start_lat, lon=body.start_lon),
        end=SegmentEndpoint(lat=body.end_lat, lon=body.end_lon),
    )
    item = ProjectItem(item_type="segment", segment=seg)

    project = ProjectIO.load(path)
    insert_at = len(project.items)  # default: append
    if body.insert_after_index is not None:
        insert_at = max(0, min(len(project.items), body.insert_after_index + 1))
    project.items.insert(insert_at, item)
    ProjectIO.save(project, path)
    return {"id": seg.id}


@router.put("/{name}/segments/{seg_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_segment(
    name: str,
    seg_id: str,
    body: SegmentBody,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Update fields of an existing connecting segment."""
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    project = ProjectIO.load(path)
    for item in project.items:
        if item.item_type == "segment" and item.segment and item.segment.id == seg_id:
            item.segment.segment_type = body.segment_type
            item.segment.label = body.label
            item.segment.start = SegmentEndpoint(lat=body.start_lat, lon=body.start_lon)
            item.segment.end = SegmentEndpoint(lat=body.end_lat, lon=body.end_lon)
            ProjectIO.save(project, path)
            return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")


@router.delete("/{name}/segments/{seg_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_segment(
    name: str,
    seg_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Remove a connecting segment from the project."""
    user_id = current_user["sub"]
    pdir = _projects_dir(user_id)
    path = os.path.join(pdir, name + ProjectIO.EXTENSION)
    if not os.path.exists(path):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    project = ProjectIO.load(path)
    original_len = len(project.items)
    project.items = [
        i for i in project.items
        if not (i.item_type == "segment" and i.segment and i.segment.id == seg_id)
    ]
    if len(project.items) == original_len:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")
    ProjectIO.save(project, path)
