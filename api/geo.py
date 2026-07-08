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

import polyline as polyline_lib
import requests
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
    """Invalidate every full-res GeoJSON cache entry for this project.

    The cache keys on (user_info_id, name, encoded) so both the expanded and
    encoded payload variants are dropped.
    """
    with _geo_cache_lock:
        for key in [k for k in _geo_cache if k[0] == user_info_id and k[1] == project_name]:
            _geo_cache.pop(key, None)


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


# ── City autocomplete (issue #49) ──────────────────────────────────────────────
# Proxies OpenStreetMap Nominatim so the Flutter web client isn't blocked by CORS
# and the shared usage policy (a descriptive User-Agent, modest volume — the
# client debounces) stays on the server. We store only the display string.
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_PLACES_UA = "ViewTrip/1.0 (city autocomplete; https://github.com/rui-nar/ViewTripWeb)"


def _nominatim_search(q: str) -> List[Dict[str, Any]]:
    """Raw Nominatim search for *q* (extracted so tests can stub the upstream)."""
    resp = requests.get(
        _NOMINATIM_URL,
        params={"q": q, "format": "jsonv2", "addressdetails": 1,
                "limit": 8, "accept-language": "en"},
        headers={"User-Agent": _PLACES_UA},
        timeout=6,
    )
    resp.raise_for_status()
    return resp.json()


def _place_label(result: Dict[str, Any]) -> str | None:
    """Reduce a Nominatim result to a 'City, Country' label, or None.

    Requires a settlement-level field in the address (city/town/village/…); a
    result carrying only a country or a non-settlement name is dropped, so the
    suggestions stay cities rather than arbitrary places.
    """
    addr = result.get("address") or {}
    city = (addr.get("city") or addr.get("town") or addr.get("village")
            or addr.get("municipality") or addr.get("hamlet"))
    if not city:
        return None
    country = addr.get("country")
    return f"{city}, {country}" if country else city


@router.get("/places", summary="City autocomplete for a person's residence")
def places(
    q: str,
    current_user: Annotated[dict, Depends(get_current_user)],
) -> List[str]:
    """Return up to a handful of distinct 'City, Country' suggestions for *q*."""
    q = q.strip()
    if len(q) < 2:
        return []
    try:
        raw = _nominatim_search(q)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    seen: set[str] = set()
    out: List[str] = []
    for result in raw:
        label = _place_label(result)
        if label and label not in seen:
            seen.add(label)
            out.append(label)
    return out


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


def _build_full_geo_features(project: Project, encoded: bool = False) -> List[Dict[str, Any]]:
    """Build the full-resolution GeoJSON features for *project*.

    When ``encoded`` is True, activities with a GPS track carry their
    Google-encoded ``summary_polyline`` verbatim in ``properties.polyline`` with
    an empty ``coordinates`` array; the client decodes it back to
    ``[[lon, lat], …]``. This keeps the payload an order of magnitude smaller
    than expanding every point server-side (a 120-activity trip drops from
    ~17.7 MB to a couple of MB) and skips the server-side decode.

    When ``encoded`` is False (the default), activity polylines are expanded to
    full ``coordinates`` server-side. This is the backward-compatible format any
    client renders directly; a client that doesn't decode encoded polylines (an
    older build) would otherwise show nothing for those activities. Only clients
    that opt in via ``?encoded=1`` receive the compact form.

    Activities without a polyline (GPX/private) fall back to a two-point
    straight line. Segments always use expanded coordinates (already short).
    """
    features: List[Dict[str, Any]] = []
    for item in project.items:
        if item.item_type == "activity":
            activity = project.activity_by_id(item.activity_id)
            if activity is None:
                continue

            if activity.summary_polyline and encoded:
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
            elif activity.summary_polyline:
                # Expanded form — decode server-side so any client renders it.
                decoded = polyline_lib.decode(activity.summary_polyline)
                coords = [[lon, lat] for lat, lon in decoded]
                if len(coords) < 2:
                    continue
                features.append(_linestring(coords, {
                    "type": "activity",
                    "activity_id": activity.id,
                    "name": activity.name,
                    "sport_type": activity.type,
                }))
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
    """Recompute and cache both full-res GeoJSON variants for a project.

    Called from background tasks right after ``bust_geo_cache`` so that the next
    edit-mode load is a fast cache HIT instead of a cold recompute (which, on a
    spinning-disk NAS, can exceed the client timeout and leave activities as
    low-res straight lines). Warms both the encoded and expanded payloads so a
    client on either format gets a HIT. Best-effort: any failure is swallowed
    since the endpoint will simply recompute on demand.
    """
    try:
        with get_session() as sess:
            project = _repo.get_project(sess, user_info_id, name, include_elevation=False)
        if project is None:
            return
        with _geo_cache_lock:
            for enc in (True, False):
                _geo_cache[(user_info_id, name, enc)] = _gzip_geo(
                    _build_full_geo_features(project, encoded=enc))
    except Exception:
        pass


@router.get("/project", summary="Full-resolution GeoJSON (gzip)")
def project_geo(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    encoded: bool = False,
):
    """Return a GeoJSON FeatureCollection for *name*.

    Pass ``encoded=1`` to receive activity tracks as Google-encoded ``polyline``
    properties (empty ``coordinates``) for a much smaller payload — the client
    decodes them. The default (``encoded=0``) expands every activity polyline to
    full ``coordinates`` server-side so any client renders it directly. GPX/
    private activities always use a two-point ``coordinates`` line; segments
    always use expanded ``coordinates``. GeoJSON coordinates are
    [longitude, latitude] as per the spec.
    """
    user_info_id = int(current_user["sub"])
    cache_key = (user_info_id, name, encoded)
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

    gz_bytes = _gzip_geo(_build_full_geo_features(project, encoded=encoded))
    with _geo_cache_lock:
        _geo_cache[cache_key] = gz_bytes
    return Response(
        content=gz_bytes,
        media_type="application/json",
        headers={"Content-Encoding": "gzip", "X-Cache": "MISS"},
    )
