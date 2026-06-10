"""GeoJSON endpoints — converts a project's tracks and segments to GeoJSON.

Routes:
    GET /api/geo/project?name=   — GeoJSON FeatureCollection for an open project
"""
from __future__ import annotations

import gzip as gzip_lib
import json
import os
from threading import Lock
from typing import Annotated, Any, Dict, List

from models.db import get_session
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from api.deps import get_current_user
from src.models.great_circle import great_circle_points
from src.models.project import Project
from src.project.project_io import ProjectIO
from src.project.project_repo import ProjectRepo, _compute_low_res_geo

router = APIRouter(prefix="/api/geo", tags=["geo"])

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_repo = ProjectRepo()

# In-memory full-res GeoJSON cache: (user_info_id, project_name) → gzip-compressed JSON bytes
_geo_cache: dict[tuple, bytes] = {}
_geo_cache_lock = Lock()


def bust_geo_cache(user_info_id: int, project_name: str) -> None:
    """Invalidate the full-res GeoJSON cache entry for this project."""
    with _geo_cache_lock:
        _geo_cache.pop((user_info_id, project_name), None)


def _legacy_path(user_id: str, name: str) -> str:
    path = os.path.join(_DATA_DIR, "users", user_id, "projects")
    os.makedirs(path, exist_ok=True)
    return os.path.join(path, name + ProjectIO.EXTENSION)


def _linestring(coords: List[List[float]], properties: Dict[str, Any]) -> Dict[str, Any]:
    """Build a GeoJSON Feature with a LineString geometry."""
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": coords,  # [[lon, lat], ...]
        },
        "properties": properties,
    }


@router.get("/project/low-res", summary="Low-res GeoJSON for fast map render")
def project_geo_low_res(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return low-res GeoJSON — straight lines per activity, arcs per segment.

    Always computed from the live project (no cached ``low_res_geo_json``
    column) so segment arcs are always present regardless of when the DB row
    was last saved.  No GPS polyline decoding occurs here — activities use
    two-point straight lines — so this is fast enough to compute on every
    request.
    """
    user_info_id = int(current_user["sub"])
    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    return json.loads(_compute_low_res_geo(project))


def _build_full_geo_features(project: Project) -> List[Dict[str, Any]]:
    """Build the full-resolution GeoJSON features for *project*.

    Activities with a GPS track carry their Google-encoded ``summary_polyline``
    verbatim in ``properties.polyline`` with an empty ``coordinates`` array; the
    client decodes it back to ``[[lon, lat], …]``. This keeps the payload an
    order of magnitude smaller than expanding every point server-side (a
    120-activity trip drops from ~17.7 MB to a couple of MB) and skips the
    server-side decode entirely. Activities without a polyline (GPX/private)
    fall back to a two-point straight line in ``coordinates``. Segments always
    use expanded coordinates (their polylines are already short).
    """
    features: List[Dict[str, Any]] = []
    for item in project.items:
        if item.item_type == "activity":
            activity = project.activity_by_id(item.activity_id)
            if activity is None:
                continue

            if activity.summary_polyline:
                # Pass the Google-encoded polyline through untouched; the client
                # decodes it. No server-side decode, tiny payload.
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": []},
                    "properties": {
                        "type": "activity",
                        "activity_id": activity.id,
                        "name": activity.name,
                        "sport_type": activity.type,
                        "polyline": activity.summary_polyline,
                    },
                })
            elif activity.start_latlng and activity.end_latlng:
                # No polyline (GPX import / private activity) — straight line fallback
                coords = [
                    [activity.start_latlng[1], activity.start_latlng[0]],
                    [activity.end_latlng[1],   activity.end_latlng[0]],
                ]
                features.append(_linestring(coords, {
                    "type": "activity",
                    "activity_id": activity.id,
                    "name": activity.name,
                    "sport_type": activity.type,
                }))
            else:
                continue  # no coordinates at all

        elif item.item_type == "segment" and item.segment is not None:
            seg = item.segment
            if seg.route_mode in ("rail", "ferry", "bus") and seg.route_polyline:
                coords = json.loads(seg.route_polyline)
            else:
                # great_circle_points returns [(lat, lon), ...]
                pts = great_circle_points(
                    seg.start.lat, seg.start.lon,
                    seg.end.lat, seg.end.lon,
                    n_points=50,
                )
                coords = [[lon, lat] for lat, lon in pts]
            if len(coords) < 2:
                continue
            features.append(_linestring(coords, {
                "type": "segment",
                "segment_id": seg.id,
                "segment_type": seg.segment_type,
                "label": seg.label,
                "route_mode": seg.route_mode,
            }))

    return features


def _gzip_geo(features: List[Dict[str, Any]]) -> bytes:
    json_bytes = json.dumps({"type": "FeatureCollection", "features": features}).encode()
    return gzip_lib.compress(json_bytes, compresslevel=6)


def warm_geo_cache(user_info_id: int, name: str) -> None:
    """Recompute and cache the full-res GeoJSON for a project.

    Called from background tasks right after ``bust_geo_cache`` so that the next
    edit-mode load is a fast cache HIT instead of a cold recompute (which, on a
    spinning-disk NAS, can exceed the client timeout and leave activities as
    low-res straight lines). Best-effort: any failure is swallowed since the
    endpoint will simply recompute on demand.
    """
    try:
        with get_session() as sess:
            project = _repo.get_project(sess, user_info_id, name, include_elevation=False)
        if project is None:
            return
        gz_bytes = _gzip_geo(_build_full_geo_features(project))
        with _geo_cache_lock:
            _geo_cache[(user_info_id, name)] = gz_bytes
    except Exception:
        pass


@router.get("/project", summary="Full-resolution GeoJSON (gzip)")
def project_geo(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
):
    """Return a GeoJSON FeatureCollection for *name*.

    Each activity feature has properties ``{"type": "activity", …}``; activities
    with a GPS track carry a Google-encoded ``polyline`` property (empty
    ``coordinates``) that the client decodes, while GPX/private activities use a
    two-point ``coordinates`` line. Each connecting segment has expanded
    ``coordinates`` with properties ``{"type": "segment", …}``. GeoJSON
    coordinates are [longitude, latitude] as per the spec.
    """
    user_info_id = int(current_user["sub"])
    cache_key = (user_info_id, name)
    with _geo_cache_lock:
        cached_bytes = _geo_cache.get(cache_key)
    if cached_bytes is not None:
        return Response(
            content=cached_bytes,
            media_type="application/json",
            headers={"Content-Encoding": "gzip", "X-Cache": "HIT"},
        )

    with get_session() as sess:
        project = _repo.get_project(
            sess, user_info_id, name,
            legacy_path=_legacy_path(current_user["sub"], name),
            include_elevation=False,
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    gz_bytes = _gzip_geo(_build_full_geo_features(project))
    with _geo_cache_lock:
        _geo_cache[cache_key] = gz_bytes
    return Response(
        content=gz_bytes,
        media_type="application/json",
        headers={"Content-Encoding": "gzip", "X-Cache": "MISS"},
    )
