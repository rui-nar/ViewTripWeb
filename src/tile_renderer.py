"""Raster-tile generation for project tracks.

Tiles are rendered with Pillow and cached to disk keyed by share_token.
The cache directory is `data/tiles/{token}/{z}/{x}/{y}.png`.

Lifecycle
---------
* On first tile request for a token, features are loaded from the DB (once,
  via get_or_build_features) and stored in an in-memory cache.  A background
  thread pool then pre-renders every tile at zoom 0–_PRERENDER_MAX_ZOOM that
  actually intersects a track segment so subsequent requests are served from disk.

* When the project is modified, callers invoke refresh_tile_cache(token, build_fn).
  This cancels any queued render job, clears both caches, and immediately
  schedules a fresh pre-render using build_fn to load the updated features.
  Rapid consecutive edits only ever run one render (the latest one).

* invalidate_tile_cache(token) is a plain clear with no re-render (used when
  a share token is revoked).
"""
from __future__ import annotations

import concurrent.futures
import io
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import mercantile
from PIL import Image, ImageDraw

TILE_SIZE = 512
_CACHE_ROOT = Path(__file__).parent.parent / "data" / "tiles"

# Pre-render tiles up to this zoom on first access / after edits.
# Only tiles that intersect track segments are rendered (not the full bbox).
_PRERENDER_MAX_ZOOM = 14

_TRACK_RGBA = (249, 115, 22, 200)   # orange — matches client 0xFFF97316
_SEG_RGBA   = (136, 136, 136, 200)  # gray   — matches client 0xFF888888
_LINE_WIDTH = 6

# ── In-memory feature cache ───────────────────────────────────────────────────
_feature_cache: Dict[str, List[Dict[str, Any]]] = {}
_feature_cache_lock = threading.Lock()

# ── Background pre-render pool + pending-job tracker ─────────────────────────
_prerender_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="tile-prerender"
)
# token → the most recently submitted Future; used to cancel queued (not yet
# running) jobs when the project is edited again before rendering completes.
_pending_futures: Dict[str, concurrent.futures.Future] = {}
_pending_lock = threading.Lock()


# ── Rendering helpers ─────────────────────────────────────────────────────────

def _to_pixel(lon: float, lat: float, bounds: mercantile.Bounds) -> Tuple[float, float]:
    west, south, east, north = bounds.west, bounds.south, bounds.east, bounds.north
    x = (lon - west) / (east - west) * TILE_SIZE
    y = (north - lat) / (north - south) * TILE_SIZE
    return x, y


def _annotate_bboxes(features: List[Dict[str, Any]]) -> None:
    """Add a cached _bbox=(min_lon, min_lat, max_lon, max_lat) to each feature in-place.

    Called once per build so render_tile can skip features that can't intersect a
    given tile with a 4-comparison check instead of iterating all coordinates.
    """
    for feat in features:
        if "_bbox" in feat:
            continue
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) >= 2:
            lons = [float(c[0]) for c in coords]
            lats = [float(c[1]) for c in coords]
            feat["_bbox"] = (min(lons), min(lats), max(lons), max(lats))


def render_tile(features: List[Dict[str, Any]], z: int, x: int, y: int) -> bytes:
    """Render GeoJSON features onto a transparent TILE_SIZE×TILE_SIZE PNG and return bytes."""
    bounds = mercantile.bounds(x, y, z)
    img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    tb_w, tb_s, tb_e, tb_n = bounds.west, bounds.south, bounds.east, bounds.north

    for feat in features:
        bbox = feat.get("_bbox")
        if bbox and (bbox[2] < tb_w or bbox[0] > tb_e or bbox[3] < tb_s or bbox[1] > tb_n):
            continue
        coords: list = (feat.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        ftype = (feat.get("properties") or {}).get("type", "activity")
        color = _SEG_RGBA if ftype == "segment" else _TRACK_RGBA
        pixels = [_to_pixel(lon, lat, bounds) for lon, lat in coords]
        draw.line(pixels, fill=color, width=_LINE_WIDTH)

    buf = io.BytesIO()
    img.save(buf, format="PNG", compress_level=1)
    return buf.getvalue()


def _bbox_from_features(
    features: List[Dict[str, Any]],
) -> Optional[Tuple[float, float, float, float]]:
    lons: List[float] = []
    lats: List[float] = []
    for feat in features:
        for c in (feat.get("geometry") or {}).get("coordinates") or []:
            if len(c) >= 2:
                lons.append(float(c[0]))
                lats.append(float(c[1]))
    if not lons:
        return None
    pad = 0.05
    return min(lons) - pad, min(lats) - pad, max(lons) + pad, max(lats) + pad


# ── Pre-render task ───────────────────────────────────────────────────────────

def _tiles_for_features(features: List[Dict[str, Any]], z: int) -> set:
    """Return the set of tiles at zoom z that any feature segment passes through.

    Samples each consecutive coordinate pair at sub-tile density so no
    intersecting tile is missed without inflating counts via a bbox expansion.
    """
    tile_deg = 360.0 / (1 << z)
    tiles: set = set()
    for feat in features:
        coords = (feat.get("geometry") or {}).get("coordinates") or []
        for i in range(len(coords) - 1):
            lon1, lat1 = float(coords[i][0]),     float(coords[i][1])
            lon2, lat2 = float(coords[i + 1][0]), float(coords[i + 1][1])
            span = max(abs(lon2 - lon1), abs(lat2 - lat1))
            n = max(2, int(span / tile_deg * 2) + 2)
            for j in range(n):
                t = j / (n - 1)
                lon = max(-180.0, min(180.0, lon1 + t * (lon2 - lon1)))
                lat = max(-85.051129, min(85.051129, lat1 + t * (lat2 - lat1)))
                tiles.add(mercantile.tile(lon, lat, z))
    return tiles


def _do_prerender(token: str, features: List[Dict[str, Any]]) -> None:
    """Render and cache only tiles that intersect track segments, zoom 0–max."""
    if not _bbox_from_features(features):
        return
    for z in range(_PRERENDER_MAX_ZOOM + 1):
        for tile in _tiles_for_features(features, z):
            path = _CACHE_ROOT / token / str(tile.z) / str(tile.x) / f"{tile.y}.png"
            if path.exists():
                continue
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(render_tile(features, tile.z, tile.x, tile.y))
            except Exception:
                pass  # best-effort; never crash the background thread


def _submit_prerender(token: str, features: List[Dict[str, Any]]) -> None:
    """Submit a pre-render job, replacing any previously queued (not running) job."""
    def _job() -> None:
        _do_prerender(token, features)
        # Clean up the futures dict once finished so the entry doesn't linger.
        with _pending_lock:
            _pending_futures.pop(token, None)

    with _pending_lock:
        old = _pending_futures.pop(token, None)
        if old is not None:
            old.cancel()
        _pending_futures[token] = _prerender_pool.submit(_job)


# ── Public API ────────────────────────────────────────────────────────────────

def get_or_build_features(
    token: str,
    build: Callable[[], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return cached features, or compute via build() then cache and pre-render.

    build() is called at most once per token across all concurrent requests.
    On the first call a background pre-render is scheduled automatically.
    """
    with _feature_cache_lock:
        if token in _feature_cache:
            return _feature_cache[token]
    features = build()
    _annotate_bboxes(features)
    with _feature_cache_lock:
        _feature_cache[token] = features
    # Only schedule if not already rendering (avoids duplicate jobs on cold start).
    with _pending_lock:
        already = token in _pending_futures
    if not already:
        _submit_prerender(token, features)
    return features


def get_cached_tile(token: str, z: int, x: int, y: int) -> Optional[bytes]:
    """Return cached PNG bytes if the tile exists on disk, otherwise None."""
    path = _CACHE_ROOT / token / str(z) / str(x) / f"{y}.png"
    return path.read_bytes() if path.exists() else None


def get_or_create_tile(
    token: str,
    features: List[Dict[str, Any]],
    z: int,
    x: int,
    y: int,
) -> bytes:
    """Return cached PNG bytes, generating and saving to disk on cache miss."""
    path = _CACHE_ROOT / token / str(z) / str(x) / f"{y}.png"
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = render_tile(features, z, x, y)
    path.write_bytes(data)
    return data


def refresh_tile_cache(
    token: str,
    build: Callable[[], List[Dict[str, Any]]],
) -> None:
    """Invalidate all caches and schedule a fresh pre-render via build().

    Call this after any project mutation.  If a render is already queued it is
    cancelled so only the latest edit's state is ever rendered.  build() is
    called inside the background thread, so the API response returns immediately.
    """
    d = _CACHE_ROOT / token
    if d.exists():
        shutil.rmtree(d)
    with _feature_cache_lock:
        _feature_cache.pop(token, None)

    def _job() -> None:
        features = build()
        _annotate_bboxes(features)
        with _feature_cache_lock:
            _feature_cache[token] = features
        _do_prerender(token, features)
        with _pending_lock:
            _pending_futures.pop(token, None)

    with _pending_lock:
        old = _pending_futures.pop(token, None)
        if old is not None:
            old.cancel()
        _pending_futures[token] = _prerender_pool.submit(_job)


def invalidate_tile_cache(token: str) -> None:
    """Clear disk cache, feature cache, and cancel any pending render (no re-render).

    Use this when a share token is revoked rather than when a project is edited.
    """
    d = _CACHE_ROOT / token
    if d.exists():
        shutil.rmtree(d)
    with _feature_cache_lock:
        _feature_cache.pop(token, None)
    with _pending_lock:
        old = _pending_futures.pop(token, None)
        if old is not None:
            old.cancel()
