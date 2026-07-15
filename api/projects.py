"""REST projects endpoints — list, create, open, update, and delete projects.

Routes:
    GET    /api/projects/                — list saved projects for current user
    POST   /api/projects/                — create new project
    GET    /api/projects/{name}          — get project data (GeoJSON + metadata)
    GET    /api/projects/{name}/meta     — get project metadata (lightweight)
    GET    /api/projects/{name}/stats    — get project statistics
    PUT    /api/projects/{name}          — update project name or dates
    DELETE /api/projects/{name}          — delete a project
    PUT    /api/projects/{name}/day-meta      — update day metadata
    GET    /api/projects/{name}/sync-meta     — get sync configuration
    PUT    /api/projects/{name}/sync-meta     — update sync configuration
    PUT    /api/projects/{name}/track-style   — update track style
    PUT    /api/projects/{name}/languages     — update translation languages
    GET    /api/projects/{name}/sync/check    — check for new activities to sync

Import/export, activities, item ordering, segments, and sharing endpoints live in
their own sibling modules (api.project_transfer, api.activities, api.project_items,
api.segments, api.project_shares) — see api/project_shared.py for the infra they
all share.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Annotated, Any, Dict, List, Optional

from models.db import get_session
from sqlmodel import select

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.project_shared import _get_project_row, _legacy_path, _refresh_stats_background, _repo
from models.project_db import DBProject, DBProjectItem, DBProjectSyncMeta
from models.user import UserInfo, PolarstepsToken, StravaToken
from src.api.polarsteps_client import PolarstepsClient, format_step
from src.models.activity import Activity
from src.models.project import DEFAULT_SLEEPING_GROUPS
from src.project.project_io import ProjectIO
from src.project.project_repo import _compute_stats

router = APIRouter(prefix="/api/projects", tags=["projects"])


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
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Name cannot be empty")
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
    color_by_type: Optional[bool] = None
    # Keyed by activity bucket ("ride"/"run"/"hike"/"other") or segment type
    # ("flight"/"train"/"bus"/"boat"); each value e.g. {"color": "#RRGGBB",
    # "style": "solid"|"dashed"|"dotted"}.
    type_styles: Optional[Dict[str, Dict[str, Any]]] = None


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
        if body.color_by_type is not None:
            row.color_by_type = body.color_by_type
        if body.type_styles is not None:
            row.type_styles_json = json.dumps(body.type_styles)
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
