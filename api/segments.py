"""REST transport-segment endpoints — create/update/delete + async route resolution.

Routes:
    POST   /api/projects/{name}/segments                       — create a connecting segment
    PUT    /api/projects/{name}/segments/{id}                   — update a segment
    DELETE /api/projects/{name}/segments/{id}                   — delete a segment
    POST   /api/projects/{name}/segments/{id}/resolve-route     — trigger async route resolution
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Optional

from models.db import get_session

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.deps import get_current_user
from api.geo import bust_geo_cache, warm_geo_cache
from api.project_access import (
    OwnerParam,
    journal_visible_positions,
    resolve_project,
    translate_insert_after,
)
from api.project_shared import _legacy_path, _refresh_share_tiles, _refresh_stats_background, _repo
from src.models.project import ConnectingSegment, ProjectItem, SegmentEndpoint
from src.project.project_repo import StaleWriteError
from src.utils.logging import get_logger

_log = get_logger(__name__)

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ── Response schemas ──────────────────────────────────────────────────────────

class SegmentIDOut(BaseModel):
    id: str = Field(description="UUID of the newly created segment")


class RouteResolvedOut(BaseModel):
    polyline: List[List[float]] = Field(description="Resolved route as [[lon, lat], …] coordinates")
    stop_count: int = Field(description="Number of intermediate stops on the route")


class RouteResolveTriggered(BaseModel):
    """Returned by the async resolve-route trigger (HTTP 202)."""
    status: str = Field(description="Always 'pending' — resolution runs in the background")
    route_status: str = Field(description="Segment route_status after scheduling: 'pending'")


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
    Mirrors the fire-and-forget pattern of :func:`api.project_shared._refresh_share_tiles`.
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
    owner: OwnerParam = None,
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
        row = resolve_project(sess, user_info_id, name, owner)
        owner_id = row.user_info_id
        project = _repo.get_project(
            sess, owner_id, name,
            legacy_path=_legacy_path(str(owner_id), name),
        )
        if project is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
        # insert_after_index is an index into the caller's *visible* item list
        # (other users' journal items are hidden) — translate it (issue #106).
        visible = journal_visible_positions(project.items, user_info_id, owner_id)
        insert_at = translate_insert_after(visible, body.insert_after_index, len(project.items))
        project.items.insert(insert_at, item)
        _repo.save_project(sess, owner_id, project, check_version=True)
    bust_geo_cache(owner_id, name)
    background_tasks.add_task(_refresh_stats_background, owner_id, name)
    background_tasks.add_task(_refresh_share_tiles, owner_id, name)
    return {"id": seg.id}


@router.put("/{name}/segments/{seg_id}", status_code=status.HTTP_204_NO_CONTENT,
            summary="Update a transport segment")
def update_segment(
    name: str,
    seg_id: str,
    body: SegmentBody,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    owner: OwnerParam = None,
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner)
        owner_id = row.user_info_id
        project = _repo.get_project(
            sess, owner_id, name,
            legacy_path=_legacy_path(str(owner_id), name),
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
                _repo.save_project(sess, owner_id, project, check_version=True)
                bust_geo_cache(owner_id, name)
                background_tasks.add_task(_refresh_stats_background, owner_id, name)
                background_tasks.add_task(_refresh_share_tiles, owner_id, name)
                return
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Segment not found")


@router.delete("/{name}/segments/{seg_id}", status_code=status.HTTP_204_NO_CONTENT,
               summary="Delete a transport segment")
def delete_segment(
    name: str,
    seg_id: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    background_tasks: BackgroundTasks,
    owner: OwnerParam = None,
):
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner)
        owner_id = row.user_info_id
        project = _repo.get_project(
            sess, owner_id, name,
            legacy_path=_legacy_path(str(owner_id), name),
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
        _repo.save_project(sess, owner_id, project, check_version=True)
    bust_geo_cache(owner_id, name)
    background_tasks.add_task(_refresh_stats_background, owner_id, name)
    background_tasks.add_task(_refresh_share_tiles, owner_id, name)


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
    owner: OwnerParam = None,
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
        row = resolve_project(sess, user_info_id, name, owner)
        owner_id = row.user_info_id
        project = _repo.get_project(
            sess, owner_id, name,
            legacy_path=_legacy_path(str(owner_id), name),
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
        _repo.save_project(sess, owner_id, project, check_version=True)
    bust_geo_cache(owner_id, name)

    background_tasks.add_task(
        _resolve_route_job, owner_id, name, seg_id, body.model_dump()
    )
    return {"status": "pending", "route_status": "pending"}
