"""Public share endpoints — no authentication required.

Routes:
    GET /api/share/{token}                      — project details for a shared link
    GET /api/share/{token}/geo                  — GeoJSON for a shared project
    GET /api/share/{token}/tiles/{z}/{x}/{y}.png — raster track tile (cached)

Both the full-project token and the no-memories token are accepted by every
endpoint.  Visit events are recorded in DBShareVisit for the project owner.
"""
from __future__ import annotations

import time
from typing import Annotated, Any, Dict, List, Optional

import polyline as polyline_lib
from models.db import get_session
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from sqlmodel import select

from api.deps import get_optional_current_user
from models.project_db import DBProject, DBShareVisit
from models.user import UserInfo
from src.models.great_circle import great_circle_points
from src.project.project_repo import ProjectRepo
from src.tile_renderer import get_cached_tile, get_or_build_features, get_or_create_tile

router = APIRouter(prefix="/api/share", tags=["share"])

_repo = ProjectRepo()


def _get_project_and_type(token: str):
    """Look up a project by either share token.

    Returns (project, token_type, project_id, owner_user_info_id).
    token_type is "full" or "no_memories".  Raises 404 if neither matches.
    """
    with get_session() as sess:
        row = sess.exec(
            select(DBProject).where(DBProject.share_token == token)
        ).first()
        if row is not None:
            token_type = "full"
        else:
            row = sess.exec(
                select(DBProject).where(
                    DBProject.share_token_no_memories == token
                )
            ).first()
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Shared project not found",
                )
            token_type = "no_memories"
        project = _repo.get_project_by_id(sess, row.id)
        project_id = row.id
        owner_user_info_id = row.user_info_id
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared project not found",
        )
    return project, token_type, project_id, owner_user_info_id


def _record_visit(
    project_id: int,
    token_type: str,
    aid: Optional[str],
    current_user: Optional[dict],
) -> None:
    """Upsert a visit record.  Errors are swallowed so they never affect the response."""
    try:
        now = time.time()
        with get_session() as sess:
            if current_user is not None:
                user_info_id = int(current_user["sub"])
                existing = sess.exec(
                    select(DBShareVisit).where(
                        DBShareVisit.project_id == project_id,
                        DBShareVisit.token_type == token_type,
                        DBShareVisit.user_info_id == user_info_id,
                    )
                ).first()
                if existing:
                    existing.last_seen_at = now
                    sess.add(existing)
                else:
                    sess.add(DBShareVisit(
                        project_id=project_id,
                        token_type=token_type,
                        visitor_type="registered",
                        user_info_id=user_info_id,
                        first_seen_at=now,
                        last_seen_at=now,
                    ))
            elif aid:
                existing = sess.exec(
                    select(DBShareVisit).where(
                        DBShareVisit.project_id == project_id,
                        DBShareVisit.token_type == token_type,
                        DBShareVisit.anonymous_id == aid,
                    )
                ).first()
                if existing:
                    existing.last_seen_at = now
                    sess.add(existing)
                else:
                    sess.add(DBShareVisit(
                        project_id=project_id,
                        token_type=token_type,
                        visitor_type="anonymous",
                        anonymous_id=aid,
                        first_seen_at=now,
                        last_seen_at=now,
                    ))
            sess.commit()
    except Exception:
        pass


@router.get("/{token}")
def shared_project(
    token: str,
    aid: Optional[str] = Query(default=None),
    current_user: Annotated[Optional[dict], Depends(get_optional_current_user)] = None,
):
    """Return project details (same shape as GET /api/projects/{name}).

    Memory items are stripped from the response when the no-memories token is used.
    """
    project, token_type, project_id, owner_uid = _get_project_and_type(token)
    _record_visit(project_id, token_type, aid, current_user)
    result = _repo.to_dict(project)
    if token_type == "no_memories":
        result["items"] = [
            item for item in (result.get("items") or [])
            if item.get("item_type") != "memory"
        ]
    with get_session() as sess:
        owner = sess.exec(
            select(UserInfo).where(UserInfo.id == owner_uid)
        ).first()
    result["owner_name"] = owner.display_name if owner else ""
    return result


def _build_features(project) -> List[Dict[str, Any]]:
    """Build GeoJSON-style feature dicts for all activities and segments."""
    features: List[Dict[str, Any]] = []

    for item in project.items:
        if item.item_type == "activity":
            activity = project.activity_by_id(item.activity_id)
            if activity is None:
                continue

            if activity.summary_polyline:
                decoded = polyline_lib.decode(activity.summary_polyline)
                coords = [[lon, lat] for lat, lon in decoded]
            elif activity.start_latlng and activity.end_latlng:
                coords = [
                    [activity.start_latlng[1], activity.start_latlng[0]],
                    [activity.end_latlng[1],   activity.end_latlng[0]],
                ]
            else:
                continue

            if len(coords) < 2:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "type": "activity",
                    "activity_id": activity.id,
                    "name": activity.name,
                    "sport_type": activity.type,
                },
            })

        elif item.item_type == "segment" and item.segment is not None:
            seg = item.segment
            pts = great_circle_points(
                seg.start.lat, seg.start.lon,
                seg.end.lat, seg.end.lon,
                n_points=50,
            )
            coords = [[lon, lat] for lat, lon in pts]
            if len(coords) < 2:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "type": "segment",
                    "segment_id": seg.id,
                    "segment_type": seg.segment_type,
                    "label": seg.label,
                },
            })

    return features


@router.get("/{token}/geo/low-res")
def shared_project_geo_low_res(token: str):
    """Return straight-line GeoJSON (start→end per activity) for fast initial map render."""
    project, _token_type, _project_id, _owner_uid = _get_project_and_type(token)
    features: List[Dict[str, Any]] = []
    for item in project.items:
        if item.item_type != "activity":
            continue
        activity = project.activity_by_id(item.activity_id)
        if activity is None:
            continue
        if activity.start_latlng and activity.end_latlng:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [
                        [activity.start_latlng[1], activity.start_latlng[0]],
                        [activity.end_latlng[1],   activity.end_latlng[0]],
                    ],
                },
                "properties": {
                    "type": "activity",
                    "activity_id": activity.id,
                },
            })
    return {"type": "FeatureCollection", "features": features}


@router.get("/{token}/geo")
def shared_project_geo(
    token: str,
    aid: Optional[str] = Query(default=None),
    current_user: Annotated[Optional[dict], Depends(get_optional_current_user)] = None,
):
    """Return GeoJSON FeatureCollection for a shared project."""
    project, token_type, project_id, _owner_uid = _get_project_and_type(token)
    _record_visit(project_id, token_type, aid, current_user)
    features = get_or_build_features(token, lambda: _build_features(project))
    return {"type": "FeatureCollection", "features": features}


@router.get("/{token}/tiles/{z}/{x}/{y}.png")
async def shared_project_tile(request: Request, token: str, z: int, x: int, y: int):
    """Return a cached raster tile PNG for the shared project's track layer.

    Zoom 0–10 are pre-rendered in the background on first access so panning
    and zooming are served instantly from disk.  Zoom 11–15 are rendered on
    demand but the endpoint checks for client disconnect before starting work,
    so stale requests from a previous zoom level are discarded immediately.
    """
    if not (0 <= z <= 15):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zoom level must be between 0 and 15",
        )
    # Fast path: already on disk — no DB, no render, no disconnect check needed.
    cached = get_cached_tile(token, z, x, y)
    if cached is not None:
        return Response(cached, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})

    # If the client already zoomed away, skip the expensive work entirely.
    if await request.is_disconnected():
        return Response(b"", status_code=204)

    def _compute() -> bytes:
        def _build():
            project, _tt, _pid, _uid = _get_project_and_type(token)
            return _build_features(project)
        features = get_or_build_features(token, _build)
        return get_or_create_tile(token, features, z, x, y)

    png = await run_in_threadpool(_compute)
    return Response(png, media_type="image/png",
                    headers={"Cache-Control": "public, max-age=86400"})
