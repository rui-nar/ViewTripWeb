"""Raster-tile generation for project tracks.

Tiles are rendered with Pillow and cached to disk keyed by share_token.
The cache directory is `data/tiles/{token}/{z}/{x}/{y}.png`.

On first access, features are computed from the project and stored in an
in-memory cache.  A background thread pool then pre-renders all tiles for
zoom levels 0–_PRERENDER_MAX_ZOOM within the features' bounding box so that
subsequent requests (panning, zooming) are served instantly from disk.

Callers must invoke `invalidate_tile_cache(token)` whenever the project's
visual content changes — this clears the disk cache, the feature cache, and
allows the next access to trigger a fresh pre-render.
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

TILE_SIZE = 256
_CACHE_ROOT = Path(__file__).parent.parent / "data" / "tiles"

# Pre-render all tiles from zoom 0 up to this level in the background.
# At zoom 10 a 10°×5° bounding box contains ~1 000 tiles; at zoom 12 ~17 000.
_PRERENDER_MAX_ZOOM = 10

_TRACK_RGBA = (249, 115, 22, 200)   # orange — matches client 0xFFF97316
_SEG_RGBA   = (136, 136, 136, 200)  # gray   — matches client 0xFF888888
_LINE_WIDTH = 3

# ── In-memory feature cache ───────────────────────────────────────────────────
_feature_cache: Dict[str, List[Dict[str, Any]]] = {}
_feature_cache_lock = threading.Lock()

# ── Background pre-render pool ────────────────────────────────────────────────
_prerender_pool = concurrent.futures.ThreadPoolExecutor(
    max_workers=2, thread_name_prefix="tile-prerender"
)
_prerender_submitted: set[str] = set()
_prerender_lock = threading.Lock()


# ── Rendering helpers ─────────────────────────────────────────────────────────

def _to_pixel(lon: float, lat: float, bounds: mercantile.Bounds) -> Tuple[float, float]:
    west, south, east, north = bounds.west, bounds.south, bounds.east, bounds.north
    x = (lon - west) / (east - west) * TILE_SIZE
    y = (north - lat) / (north - south) * TILE_SIZE
    return x, y


def render_tile(features: List[Dict[str, Any]], z: int, x: int, y: int) -> bytes:
    """Render GeoJSON features onto a transparent 256×256 PNG and return bytes."""
    bounds = mercantile.bounds(x, y, z)
    img = Image.new("RGBA", (TILE_SIZE, TILE_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    for feat in features:
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


# ── Pre-render background task ────────────────────────────────────────────────

def _do_prerender(token: str, features: List[Dict[str, Any]]) -> None:
    """Render and cache every tile covering the features' bbox, zoom 0–max."""
    bbox = _bbox_from_features(features)
    if bbox is None:
        return
    west, south, east, north = bbox
    for z in range(_PRERENDER_MAX_ZOOM + 1):
        for tile in mercantile.tiles(west, south, east, north, zooms=z):
            path = _CACHE_ROOT / token / str(tile.z) / str(tile.x) / f"{tile.y}.png"
            if path.exists():
                continue
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(render_tile(features, tile.z, tile.x, tile.y))
            except Exception:
                pass  # best-effort; never crash the background thread


def _schedule_prerender(token: str, features: List[Dict[str, Any]]) -> None:
    """Submit a pre-render job if one hasn't been scheduled for this token yet."""
    with _prerender_lock:
        if token in _prerender_submitted:
            return
        _prerender_submitted.add(token)
    _prerender_pool.submit(_do_prerender, token, features)


# ── Public API ────────────────────────────────────────────────────────────────

def get_or_build_features(
    token: str,
    build: Callable[[], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return cached features, or compute them via build() and cache + pre-render.

    build() is called at most once per token across all concurrent requests.
    After the first computation the background pre-render is scheduled so that
    tiles at zoom 0–_PRERENDER_MAX_ZOOM are ready before the client asks for them.
    """
    with _feature_cache_lock:
        if token in _feature_cache:
            return _feature_cache[token]
    features = build()
    with _feature_cache_lock:
        _feature_cache[token] = features
    _schedule_prerender(token, features)
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


def invalidate_tile_cache(token: str) -> None:
    """Delete disk cache, in-memory feature cache, and pre-render state for a token."""
    d = _CACHE_ROOT / token
    if d.exists():
        shutil.rmtree(d)
    with _feature_cache_lock:
        _feature_cache.pop(token, None)
    with _prerender_lock:
        _prerender_submitted.discard(token)
