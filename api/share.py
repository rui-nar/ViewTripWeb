"""Public share endpoints — no authentication required.

Routes:
    GET /api/share/{token}                                     — project details for a shared link
    GET /api/share/{token}/meta                                — lightweight details (no elevation/polylines)
    GET /api/share/{token}/geo                                 — GeoJSON for a shared project
    GET /api/share/{token}/stats                               — project statistics (no auth required)
    GET /api/share/{token}/tiles/{z}/{x}/{y}.png               — raster track tile (cached)
    GET /api/share/{token}/photos/{memory_id}/{uuid}/thumb     — memory photo thumbnail (no auth)
    GET /api/share/{token}/photos/{memory_id}/{uuid}           — memory photo full-res (no auth)

Both the full-project token and the no-memories token are accepted by every
endpoint.  Visit events are recorded in DBShareVisit for the project owner.
"""
from __future__ import annotations

import json
import os
import time
import threading
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional


class _TTLCache:
    """Minimal thread-safe in-process TTL cache — no external dependencies."""

    def __init__(self, ttl: float = 60.0) -> None:
        self._ttl = ttl
        self._data: dict = {}
        self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            entry = self._data.get(key)
        if entry is None:
            return None
        value, exp = entry
        if time.monotonic() > exp:
            with self._lock:
                self._data.pop(key, None)
            return None
        return value

    def set(self, key, value) -> None:
        with self._lock:
            self._data[key] = (value, time.monotonic() + self._ttl)

    def delete(self, key) -> None:
        with self._lock:
            self._data.pop(key, None)


# Keyed by share token.  TTL is intentionally short so edits propagate quickly.
_project_cache: _TTLCache = _TTLCache(ttl=60.0)       # full project object
_project_meta_cache: _TTLCache = _TTLCache(ttl=60.0)  # lightweight project object (no polyline/elevation)
_details_cache: _TTLCache = _TTLCache(ttl=60.0)        # serialised full-details dict
_meta_cache: _TTLCache = _TTLCache(ttl=60.0)           # serialised stripped-details dict


def invalidate_share_cache(token: str) -> None:
    """Evict all cached entries for *token*. Call after any project mutation."""
    _project_cache.delete(token)
    _project_meta_cache.delete(token)
    _details_cache.delete(token)
    _meta_cache.delete(token)

import polyline as polyline_lib
from models.db import get_session
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response
from sqlmodel import select

from api.deps import get_optional_current_user
from models.project_db import DBMemory, DBMemoryComment, DBMemoryLike, DBProject, DBShareVisit
from models.user import UserInfo

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
from src.models.great_circle import great_circle_points
from src.project.project_repo import ProjectRepo, _compute_stats
from src.tile_renderer import get_cached_tile, get_or_build_features, get_or_create_tile

router = APIRouter(prefix="/api/share", tags=["share"])

_repo = ProjectRepo()


def _get_project_and_type(token: str):
    """Look up a project by either share token.

    Returns (project, token_type, project_id, owner_user_info_id).
    token_type is "full" or "no_memories".  Raises 404 if neither matches.
    Result is cached for 60 s to avoid repeated DB + repo work on the same token.
    """
    cached = _project_cache.get(token)
    if cached is not None:
        return cached

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
    result = (project, token_type, project_id, owner_user_info_id)
    _project_cache.set(token, result)
    return result


def _get_meta_project_and_type(token: str):
    """Lightweight variant of _get_project_and_type for the /meta endpoint.

    Uses get_project_by_id_meta() which defers summary_polyline and
    elevation_profile_json from the SQL SELECT.  On spinning-disk NAS storage
    this avoids hundreds of SQLite overflow-page reads, dropping cold meta load
    from ~19 s to under 1 s.

    Falls back to the full _project_cache if already warm so we never load the
    project twice when the full endpoint was called first.
    """
    # If the full project is already cached, it has everything meta needs too.
    full = _project_cache.get(token)
    if full is not None:
        return full

    # Check the lightweight meta-project cache.
    cached = _project_meta_cache.get(token)
    if cached is not None:
        return cached

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
        project = _repo.get_project_by_id_meta(sess, row.id)
        project_id = row.id
        owner_user_info_id = row.user_info_id

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared project not found",
        )
    result = (project, token_type, project_id, owner_user_info_id)
    _project_meta_cache.set(token, result)
    return result


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
    cached_result = _details_cache.get(token)
    if cached_result is None:
        result = _repo.to_dict(project)
        # Journal entries are always private — strip from all shared views
        result["items"] = [
            item for item in (result.get("items") or [])
            if item.get("item_type") != "journal"
        ]
        if token_type == "no_memories":
            result["items"] = [
                item for item in result["items"]
                if item.get("item_type") != "memory"
            ]
        with get_session() as sess:
            owner = sess.exec(
                select(UserInfo).where(UserInfo.id == owner_uid)
            ).first()
        result["owner_name"] = owner.display_name if owner else ""
        _details_cache.set(token, result)
        cached_result = result
    return cached_result


@router.get("/{token}/meta")
def shared_project_meta(
    token: str,
    aid: Optional[str] = Query(default=None),
    current_user: Annotated[Optional[dict], Depends(get_optional_current_user)] = None,
):
    """Same shape as GET /{token} but with elevation_profile and map.summary_polyline
    absent from each activity.  Uses a lightweight project load that defers those
    two heavy TEXT columns from SQLite, keeping cold-cache response time under 1 s.
    """
    project, token_type, project_id, owner_uid = _get_meta_project_and_type(token)
    _record_visit(project_id, token_type, aid, current_user)

    cached = _meta_cache.get(token)
    if cached is not None:
        return cached

    # Build the response dict.  The lightweight project already has
    # elevation_profile=None and summary_polyline=None on all activities,
    # so to_dict() produces the stripped payload without extra work.
    result = _repo.to_dict(project)
    # Journal entries are always private — strip from all shared views
    result["items"] = [
        item for item in (result.get("items") or [])
        if item.get("item_type") != "journal"
    ]
    if token_type == "no_memories":
        result["items"] = [
            item for item in result["items"]
            if item.get("item_type") != "memory"
        ]
    with get_session() as sess:
        owner = sess.exec(
            select(UserInfo).where(UserInfo.id == owner_uid)
        ).first()
    result["owner_name"] = owner.display_name if owner else ""
    _meta_cache.set(token, result)
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
            if seg.route_mode == "rail" and seg.route_polyline:
                import json as _json
                coords = _json.loads(seg.route_polyline)
            else:
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
                    "route_mode": seg.route_mode,
                },
            })

    return features


@router.get("/{token}/geo/low-res")
def shared_project_geo_low_res(token: str):
    """Return low-res GeoJSON for fast initial map render.

    Activities: straight lines (start→end, no polyline decoding).
    Segments: 50-point great-circle arcs (or stored rail polylines) — same as
    the full-res endpoint.  Both appear immediately so there are no holes
    in the route during the low-res phase.
    """
    project, _token_type, _project_id, _owner_uid = _get_project_and_type(token)
    features: List[Dict[str, Any]] = []
    for item in project.items:
        if item.item_type == "activity":
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
        elif item.item_type == "segment" and item.segment is not None:
            seg = item.segment
            if seg.route_mode == "rail" and seg.route_polyline:
                coords = json.loads(seg.route_polyline)
            else:
                pts = great_circle_points(
                    seg.start.lat, seg.start.lon,
                    seg.end.lat,   seg.end.lon,
                    n_points=50,
                )
                coords = [[lon, lat] for lat, lon in pts]
            if len(coords) >= 2:
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "type": "segment",
                        "segment_id": seg.id,
                        "segment_type": seg.segment_type,
                        "label": seg.label,
                        "route_mode": seg.route_mode,
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


@router.get("/{token}/stats")
def shared_project_stats(
    token: str,
    tags: Optional[List[str]] = Query(default=None),
) -> dict:
    """Return project statistics for a shared link (no auth required)."""
    project, _token_type, project_id, _owner_uid = _get_project_and_type(token)

    if tags:
        return _compute_stats(project, tag_filter=tags)

    with get_session() as sess:
        row = sess.exec(select(DBProject).where(DBProject.id == project_id)).first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        if row.stats_json is None:
            _repo.compute_and_cache_stats(sess, row.user_info_id, row.name)
            row = sess.exec(select(DBProject).where(DBProject.id == project_id)).first()
        stats = json.loads(row.stats_json or "{}")
        stats["tag_options"] = sorted({
            t
            for dm in json.loads(row.day_meta_json or "{}").values()
            for t in (dm.get("tags") or [])
        })
    return stats


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


def _shared_photo_path(token: str, memory_id: int, photo_uuid: str, thumb: bool):
    """Resolve and validate a photo path via share token. Returns (Path, owner_uid) or raises."""
    project, token_type, _project_id, owner_uid = _get_project_and_type(token)
    if token_type == "no_memories":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    with get_session() as sess:
        mem_row = sess.get(DBMemory, memory_id)
        if mem_row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        proj_row = sess.get(DBProject, mem_row.project_id)
        if proj_row is None or proj_row.user_info_id != owner_uid:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
        photos = json.loads(mem_row.photos_json or "[]")
        if photo_uuid not in photos:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    base = Path(_DATA_DIR) / "users" / str(owner_uid) / "memories" / str(memory_id)
    suffix = "_thumb" if thumb else ""
    return base / f"{photo_uuid}{suffix}.jpg"


@router.get("/{token}/photos/{memory_id}/{photo_uuid}/thumb")
def shared_photo_thumb(token: str, memory_id: int, photo_uuid: str):
    """Serve a memory photo thumbnail without requiring user authentication."""
    path = _shared_photo_path(token, memory_id, photo_uuid, thumb=True)
    if not path.exists():
        # Fall back to full-res
        full = path.parent / f"{photo_uuid}.jpg"
        if full.exists():
            return FileResponse(str(full), media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=86400"})
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(str(path), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{token}/photos/{memory_id}/{photo_uuid}")
def shared_photo_full(token: str, memory_id: int, photo_uuid: str):
    """Serve a full-resolution memory photo without requiring user authentication."""
    path = _shared_photo_path(token, memory_id, photo_uuid, thumb=False)
    if not path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return FileResponse(str(path), media_type="image/jpeg",
                        headers={"Cache-Control": "public, max-age=86400"})


# ── Share: comments & likes ───────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel
from api.memories import _build_comment_tree, _delete_comment_subtree, _utc_now


def _resolve_shared_memory(token: str, memory_id: int):
    """Validate share token and confirm memory belongs to the shared project.

    Returns (project_id, owner_user_info_id).  Raises 404 on any mismatch.
    """
    _project, token_type, project_id, owner_uid = _get_project_and_type(token)
    if token_type == "no_memories":
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    with get_session() as sess:
        mem_row = sess.get(DBMemory, memory_id)
        if mem_row is None or mem_row.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    return project_id, owner_uid


@router.get("/{token}/memories/{memory_id}/comments")
def shared_list_comments(token: str, memory_id: int):
    _resolve_shared_memory(token, memory_id)
    with get_session() as sess:
        rows = sess.exec(
            select(DBMemoryComment)
            .where(DBMemoryComment.memory_id == memory_id)
            .order_by(DBMemoryComment.created_at)
        ).all()
        return _build_comment_tree(list(rows))


class _SharedCommentBody(_BaseModel):
    text: str
    parent_comment_id: Optional[int] = None


@router.post("/{token}/memories/{memory_id}/comments", status_code=201)
def shared_add_comment(
    token: str,
    memory_id: int,
    body: _SharedCommentBody,
    current_user: Annotated[Optional[dict], Depends(get_optional_current_user)] = None,
):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    _resolve_shared_memory(token, memory_id)
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        user_row = sess.get(UserInfo, user_info_id)
        commenter_name = user_row.display_name if user_row else ""

        if body.parent_comment_id is not None:
            parent = sess.get(DBMemoryComment, body.parent_comment_id)
            if parent is None or parent.memory_id != memory_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent comment")

        row = DBMemoryComment(
            memory_id=memory_id,
            parent_comment_id=body.parent_comment_id,
            user_info_id=user_info_id,
            commenter_name=commenter_name,
            text=body.text,
            created_at=_utc_now(),
        )
        sess.add(row)
        sess.commit()
        return {"id": row.id}


@router.delete("/{token}/memories/{memory_id}/comments/{comment_id}", status_code=204)
def shared_delete_comment(
    token: str,
    memory_id: int,
    comment_id: int,
    current_user: Annotated[Optional[dict], Depends(get_optional_current_user)] = None,
):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    _project_id, owner_uid = _resolve_shared_memory(token, memory_id)
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        comment_row = sess.get(DBMemoryComment, comment_id)
        if comment_row is None or comment_row.memory_id != memory_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Comment not found")
        is_owner = user_info_id == owner_uid
        is_author = comment_row.user_info_id == user_info_id
        if not (is_owner or is_author):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
        _delete_comment_subtree(sess, comment_id)
        sess.commit()


@router.get("/{token}/memories/{memory_id}/likes")
def shared_get_likes(
    token: str,
    memory_id: int,
    current_user: Annotated[Optional[dict], Depends(get_optional_current_user)] = None,
):
    _resolve_shared_memory(token, memory_id)
    user_info_id = int(current_user["sub"]) if current_user else None
    with get_session() as sess:
        like_rows = sess.exec(
            select(DBMemoryLike).where(DBMemoryLike.memory_id == memory_id)
        ).all()
        liked_by_me = any(r.user_info_id == user_info_id for r in like_rows) if user_info_id else False
        return {
            "count": len(like_rows),
            "liked_by_me": liked_by_me,
            "likers": [{"name": r.liker_name, "user_info_id": r.user_info_id} for r in like_rows],
        }


@router.post("/{token}/memories/{memory_id}/like", status_code=204)
def shared_like_memory(
    token: str,
    memory_id: int,
    current_user: Annotated[Optional[dict], Depends(get_optional_current_user)] = None,
):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    _resolve_shared_memory(token, memory_id)
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        existing = sess.exec(
            select(DBMemoryLike).where(
                DBMemoryLike.memory_id == memory_id,
                DBMemoryLike.user_info_id == user_info_id,
            )
        ).first()
        if existing:
            return
        user_row = sess.get(UserInfo, user_info_id)
        liker_name = user_row.display_name if user_row else ""
        sess.add(DBMemoryLike(
            memory_id=memory_id,
            user_info_id=user_info_id,
            liker_name=liker_name,
            created_at=_utc_now(),
        ))
        sess.commit()


@router.delete("/{token}/memories/{memory_id}/like", status_code=204)
def shared_unlike_memory(
    token: str,
    memory_id: int,
    current_user: Annotated[Optional[dict], Depends(get_optional_current_user)] = None,
):
    if current_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    _resolve_shared_memory(token, memory_id)
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        existing = sess.exec(
            select(DBMemoryLike).where(
                DBMemoryLike.memory_id == memory_id,
                DBMemoryLike.user_info_id == user_info_id,
            )
        ).first()
        if existing:
            sess.delete(existing)
            sess.commit()
