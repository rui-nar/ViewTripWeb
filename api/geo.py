"""GeoJSON endpoints — converts a project's tracks and segments to GeoJSON.

Routes:
    GET /api/geo/project?name=   — GeoJSON FeatureCollection for an open project
"""
from __future__ import annotations

import gzip as gzip_lib
import json
import os
import time
from threading import Lock
from time import monotonic
from typing import Annotated, Any, Dict, List

import polyline as polyline_lib
import requests
from models.db import get_session
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response

from api.deps import get_current_user
from api.project_access import OwnerParam, resolve_project
from src.models.great_circle import great_circle_points
from src.models.project import Project
from src.project.project_io import ProjectIO
from src.project.project_repo import ProjectRepo, _compute_low_res_geo
from src.jobs.redis_client import get_redis
from src.utils.encryption_check import is_encrypted_envelope
from src.utils.logging import get_logger

router = APIRouter(prefix="/api/geo", tags=["geo"])

_log = get_logger(__name__)

_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
_repo = ProjectRepo()

# In-memory cache of gzipped per-project payloads:
#   (user_info_id, project_name, variant) → (gzip JSON bytes, expiry, generation)
# where expiry is a ``monotonic()`` deadline. Entries older than that are treated
# as a MISS: the generation guard below is what actually prevents a stale entry,
# but a TTL bounds *any* future bug of that class to minutes rather than forever,
# and a recompute is already the fallback so expiring early is cheap.
# The stored generation is what the entry was computed against — compared on
# read so an invalidation from another process is honoured (issue #173).
# The variant slot distinguishes payloads of the same project: the full-res geo
# endpoint keys on its ``encoded`` flag, /meta on ("meta", caller_id) — see
# api.project_shared.meta_cache_key. Every variant of a project shares one
# generation counter, so a single bust drops them all, which is what keeps
# "one bust per mutation" sufficient as payload kinds are added (issue #178).
_geo_cache: dict[tuple, tuple[bytes, float, int]] = {}
_geo_cache_lock = Lock()
_GEO_CACHE_TTL_S = 300.0

# Per-project invalidation counter, bumped by every bust (issue #132). A reader
# captures it *before* its DB read and declines to persist its result if the
# counter moved meanwhile — otherwise a read that started before a mutation can
# refill the cache with the pre-mutation snapshot that mutation just evicted,
# wedging it there until the next bust.
# This dict is the fallback authority. When Redis is configured the counter is
# shared across processes instead — see _shared_generation (issue #173).
_geo_gen: dict[tuple, int] = {}


def _gen_redis_key(user_info_id: int, project_name: str) -> str:
    """Redis key holding a project's shared invalidation generation."""
    return f"viewtrip:geo:gen:{user_info_id}:{project_name}"


def _shared_generation(user_info_id: int, project_name: str) -> int | None:
    """The generation counter as Redis sees it, or None when it cannot answer.

    None means "no cross-process authority available" — the caller falls back to
    the process-local counter, which is exactly right in that situation: without
    a reachable broker no worker can be dispatched to, so this process is the
    only one mutating anything.
    """
    client = get_redis()
    if client is None:
        return None
    try:
        raw = client.get(_gen_redis_key(user_info_id, project_name))
        return int(raw) if raw is not None else 0
    except Exception:  # noqa: BLE001 — broker hiccup → local counter
        return None


def bust_geo_cache(user_info_id: int, project_name: str) -> None:
    """Invalidate every full-res GeoJSON cache entry for this project.

    The cache keys on (user_info_id, name, encoded) so both the expanded and
    encoded payload variants are dropped. Also bumps the project's generation
    counter so any read already in flight refuses to write its now-stale result.

    The counter lives in Redis when one is configured (issue #173). Dropping the
    local dict only invalidates *this* process's copy, so once route resolution
    runs in a worker the API process would otherwise keep serving pre-resolve
    geometry until the TTL expired — a silent staleness worse than the recompute
    it avoids. Every process compares against the shared counter on read.
    """
    client = get_redis()
    if client is not None:
        try:
            client.incr(_gen_redis_key(user_info_id, project_name))
        except Exception:  # noqa: BLE001 — local bust below still covers this process
            _log.warning("could not bump the shared geo generation for %r", project_name)

    with _geo_cache_lock:
        for key in [k for k in _geo_cache if k[0] == user_info_id and k[1] == project_name]:
            _geo_cache.pop(key, None)
        gen_key = (user_info_id, project_name)
        _geo_gen[gen_key] = _geo_gen.get(gen_key, 0) + 1


def _geo_generation(user_info_id: int, project_name: str) -> int:
    """Current invalidation generation for a project. Read before the DB load."""
    shared = _shared_generation(user_info_id, project_name)
    if shared is not None:
        return shared
    with _geo_cache_lock:
        return _geo_gen.get((user_info_id, project_name), 0)


def _geo_cache_get(cache_key: tuple) -> bytes | None:
    """Cached bytes for *cache_key*, or None when absent, expired or superseded.

    The generation check is what makes a *remote* bust visible: an entry this
    process cached is dropped when another process has since invalidated the
    project. It happens outside the lock — it may hit Redis, and holding the
    lock across a network call would serialise every cache read behind it.
    """
    with _geo_cache_lock:
        entry = _geo_cache.get(cache_key)
        if entry is None:
            return None
        gz_bytes, deadline, gen = entry
        if monotonic() >= deadline:
            _geo_cache.pop(cache_key, None)
            return None

    if gen != _geo_generation(cache_key[0], cache_key[1]):
        with _geo_cache_lock:
            _geo_cache.pop(cache_key, None)
        return None
    return gz_bytes


def _geo_cache_store(cache_key: tuple, gz_bytes: bytes, gen: int) -> None:
    """Persist *gz_bytes* only if nothing busted the project since generation *gen*.

    The caller still serves what it computed — that payload is as fresh as the
    read that produced it. We only decline to *persist* an entry that may already
    be superseded; the cost is at most a redundant recompute on the next request.
    """
    if _geo_generation(cache_key[0], cache_key[1]) != gen:
        return
    with _geo_cache_lock:
        _geo_cache[cache_key] = (gz_bytes, monotonic() + _GEO_CACHE_TTL_S, gen)


# Public names for the three primitives above, used by the other per-project
# payload caches (currently /meta, see api.project_shared). They deliberately
# share this module's state: one generation counter and one bust per project
# covers every payload kind, and the TTL + generation guards (issues #132, #173)
# exist once rather than being re-derived per endpoint.
project_cache_get = _geo_cache_get
project_cache_store = _geo_cache_store
project_cache_generation = _geo_generation
bust_project_cache = bust_geo_cache


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
    owner: OwnerParam = None,
):
    """Return low-res GeoJSON — straight lines per activity, arcs per segment.

    Always computed from the live project (no cached ``low_res_geo_json``
    column) so segment arcs are always present regardless of when the DB row
    was last saved.  No GPS polyline decoding occurs here — activities use
    two-point straight lines — so this is fast enough to compute on every
    request.

    include_heavy=False because ``_compute_low_res_geo`` reads only
    start_latlng/end_latlng and segment geometry: loading every activity's
    summary_polyline and elevation_profile_json meant paying for their overflow
    pages to build a payload that never looks at them, which on a cold cache put
    this endpoint (issue #178) at 13 s — over the client's whole load budget.
    """
    user_info_id = int(current_user["sub"])
    t0 = time.time()
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner)
        project = _repo.get_project(
            sess, row.user_info_id, name,
            legacy_path=_legacy_path(str(row.user_info_id), name),
            include_heavy=False,
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    t1 = time.time()
    payload = json.loads(_compute_low_res_geo(project))
    _log.info("geo_low_res name=%s load=%.3fs build=%.3fs",
              name, t1 - t0, time.time() - t1)
    return payload


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
            if is_encrypted_envelope(activity.summary_polyline):
                # Encrypted geometry (issue #29) — the server can't decode this;
                # skip it entirely. The client builds this activity's track
                # itself, from its own decrypted copy, once unlocked.
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
        gen = _geo_generation(user_info_id, name)
        with get_session() as sess:
            project = _repo.get_project(sess, user_info_id, name, include_elevation=False)
        if project is None:
            return
        for enc in (True, False):
            _geo_cache_store(
                (user_info_id, name, enc),
                _gzip_geo(_build_full_geo_features(project, encoded=enc)),
                gen,
            )
    except Exception:
        pass


@router.get("/project", summary="Full-resolution GeoJSON (gzip)")
def project_geo(
    name: str,
    current_user: Annotated[dict, Depends(get_current_user)],
    encoded: bool = False,
    owner: OwnerParam = None,
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
    with get_session() as sess:
        row = resolve_project(sess, user_info_id, name, owner)
        owner_id = row.user_info_id

        cache_key = (owner_id, name, encoded)
        cached_bytes = _geo_cache_get(cache_key)
        if cached_bytes is not None:
            return Response(
                content=cached_bytes,
                media_type="application/json",
                headers={"Content-Encoding": "gzip", "X-Cache": "HIT"},
            )

        gen = _geo_generation(owner_id, name)  # before the read, so a bust wins
        project = _repo.get_project(
            sess, owner_id, name,
            legacy_path=_legacy_path(str(owner_id), name),
            include_elevation=False,
        )
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    gz_bytes = _gzip_geo(_build_full_geo_features(project, encoded=encoded))
    _geo_cache_store(cache_key, gz_bytes, gen)
    return Response(
        content=gz_bytes,
        media_type="application/json",
        headers={"Content-Encoding": "gzip", "X-Cache": "MISS"},
    )
