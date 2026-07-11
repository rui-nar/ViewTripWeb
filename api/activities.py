"""REST activity endpoints — add/refresh/edit/split activities within a project.

Routes:
    POST   /api/projects/{name}/activities                          — add activities to project
    POST   /api/projects/{name}/activities/{activity_id}/refresh    — refresh activity from Strava
    GET    /api/projects/{name}/activities/{activity_id}/track      — get editable track geometry
    PUT    /api/projects/{name}/activities/{activity_id}/track      — replace track geometry
    POST   /api/projects/{name}/activities/{activity_id}/reset      — reset edited track to original
    POST   /api/projects/{name}/activities/{activity_id}/split      — split into head + local tail
    DELETE /api/projects/{name}/activities/{activity_id}/local      — delete a local (split-tail) activity
"""
from __future__ import annotations

import json
import os
import time
from typing import Annotated, Any, Dict, List, Optional

import polyline as polyline_lib
from models.db import get_session
from sqlmodel import select

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.geo import bust_geo_cache, warm_geo_cache
from api.project_shared import _get_project_row, _legacy_path, _refresh_share_tiles, _refresh_stats_background, _repo
from models.user import StravaToken
from src.api.strava_client import RateLimiter, StravaAPI
from src.config.settings import Config
from src.models.activity import Activity

_cfg = Config("config/config.json")
if os.environ.get("STRAVA_CLIENT_ID"):
    _cfg.set("strava.client_id", os.environ["STRAVA_CLIENT_ID"])
if os.environ.get("STRAVA_CLIENT_SECRET"):
    _cfg.set("strava.client_secret", os.environ["STRAVA_CLIENT_SECRET"])

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ── Response schemas ──────────────────────────────────────────────────────────

class ActivitiesAddedOut(BaseModel):
    added: int = Field(description="Number of new activities added")
    total: int = Field(description="Total activities in the project after add")
    pending_enrichment: int = Field(description="Activities queued for GPS stream enrichment in background")


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
