"""REST poster endpoints — async server-side A0 poster generation (issue #14).

Routes:
    POST /api/projects/{name}/poster                    — start a poster job
    GET  /api/projects/{name}/poster/{job_id}            — poll job status
    GET  /api/projects/{name}/poster/{job_id}/download   — download the rendered file
    POST /api/projects/{name}/poster/preview             — fast low-res layout preview

This is Unit A of the poster feature: it owns the job row, the API contract,
and a placeholder renderer (src/poster/poster_job_runner.py). Later units
replace what happens inside ``run_poster_job`` (real tile-fetching, card
placement, day metrics, rendering) without changing this contract.
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Annotated, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from fastapi.responses import FileResponse
from models.db import get_session
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.project_access import OwnerParam, resolve_project
from models.project_db import DBPosterJob
from src.poster.poster_job_runner import run_poster_job
from src.poster.poster_renderer import render_poster_preview

router = APIRouter(prefix="/api/projects", tags=["poster"])

_log = logging.getLogger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


# ── Request/response schemas ──────────────────────────────────────────────────

class BoundsIn(BaseModel):
    north: float
    south: float
    east: float
    west: float


class PosterConfigIn(BaseModel):
    distance: bool = False
    elevation: bool = False
    hero_photo: bool = False
    all_photos: bool = False
    memory_text: bool = False
    counters: bool = False
    tag_pie: bool = False
    encounters: bool = False


class PosterMemoryIn(BaseModel):
    id: int
    lat: float
    lon: float
    date: str
    name: Optional[str] = None
    description: Optional[str] = None
    photo_uuids: List[str] = Field(default_factory=list)


class PosterRequest(BaseModel):
    bounds: BoundsIn
    orientation: str = Field(description="'landscape' or 'portrait'")
    config: PosterConfigIn
    memories: List[PosterMemoryIn] = Field(default_factory=list)


class JobIdOut(BaseModel):
    job_id: int = Field(description="ID of the created poster job")


class JobStatusOut(BaseModel):
    status: str = Field(description="'pending' | 'running' | 'done' | 'failed'")
    stage: Optional[str] = Field(None, description="Human-readable progress label")
    error_message: Optional[str] = Field(None, description="Set when status='failed'")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _poster_dir(user_id: str, job_id: int) -> Path:
    p = Path(_DATA_DIR) / "users" / user_id / "posters" / str(job_id)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _get_owned_job(sess, job_id: int, user_info_id: int) -> DBPosterJob:
    """Return the DBPosterJob row, 404ing unless it exists and belongs to the caller."""
    job = sess.get(DBPosterJob, job_id)
    if job is None or job.user_info_id != user_info_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poster job not found")
    return job


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/{name}/poster", status_code=status.HTTP_201_CREATED,
             response_model=JobIdOut, summary="Start a poster generation job")
def create_poster_job(
    name: str,
    body: PosterRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    owner: OwnerParam = None,
):
    """Create a pending poster job for a project and render it in the background."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = resolve_project(sess, user_info_id, name, owner)
        job = DBPosterJob(
            project_id=project.id,
            user_info_id=user_info_id,
            status="pending",
            request_json=json.dumps(body.model_dump()),
        )
        sess.add(job)
        sess.commit()
        job_id = job.id

    background_tasks.add_task(run_poster_job, job_id)
    return {"job_id": job_id}


@router.get("/{name}/poster/{job_id}", response_model=JobStatusOut,
            summary="Get poster job status")
def get_poster_job_status(
    name: str,
    job_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    owner: OwnerParam = None,
):
    """Poll the status of a poster job."""
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        resolve_project(sess, user_info_id, name, owner)
        job = _get_owned_job(sess, job_id, user_info_id)
        return {
            "status": job.status,
            "stage": job.stage,
            "error_message": job.error_message,
        }


@router.get("/{name}/poster/{job_id}/download", summary="Download the rendered poster")
def download_poster(
    name: str,
    job_id: int,
    current_user: Annotated[dict, Depends(get_current_user)],
    format: str = Query("png", pattern="^(png|pdf)$"),
    owner: OwnerParam = None,
):
    """Return the rendered poster file once the job is done.

    404s if the job doesn't exist, isn't owned by the caller, isn't done yet, or
    the requested file is missing on disk — paths are always re-derived from the
    job row server-side, never trusted from the client.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        resolve_project(sess, user_info_id, name, owner)
        job = _get_owned_job(sess, job_id, user_info_id)
        if job.status != "done":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Poster not ready")
        path_str = job.result_png_path if format == "png" else job.result_pdf_path

    if not path_str or not Path(path_str).exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")

    media_type = "image/png" if format == "png" else "application/pdf"
    return FileResponse(path_str, media_type=media_type)


@router.post("/{name}/poster/preview", summary="Fast low-res poster layout preview")
def preview_poster(
    name: str,
    body: PosterRequest,
    current_user: Annotated[dict, Depends(get_current_user)],
    owner: OwnerParam = None,
):
    """Return a small PNG preview of the poster layout (pins/cards/legend)
    for the given request, synchronously — no job row, no background task,
    no Mapbox basemap fetch (see ``render_poster_preview``), so this returns
    in well under a second and never depends on ``MAPBOX_TOKEN``/network.
    Lets the client show what the layout will look like before committing to
    the slower full-resolution job.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner)
        project_id = row.id
        owner_id = row.user_info_id

    try:
        png_bytes = render_poster_preview(project_id, owner_id, body.model_dump())
    except Exception as exc:
        # Unlike the async job (whose failure lands in job.error_message), a
        # preview failure would otherwise surface as a bare 500 with no
        # detail — issue #14 feedback point 9 ("preview was not available")
        # was undiagnosable for exactly that reason.
        _log.exception("Poster preview render failed for project %s", name)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Preview render failed: {exc}",
        )
    return Response(content=png_bytes, media_type="image/png")
