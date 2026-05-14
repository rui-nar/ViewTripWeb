"""Lazy raster-tile generation for project tracks.

Tiles are rendered with Pillow and cached to disk keyed by share_token.
The cache directory is `data/tiles/{token}/{z}/{x}/{y}.png`.
Features (GeoJSON dicts) are also cached in memory so concurrent tile
requests for the same token only load the project from DB once.
Callers must invoke `invalidate_tile_cache(token)` whenever the project's
visual content changes — this clears both the disk cache and the feature cache.
"""
from __future__ import annotations

import io
import shutil
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import mercantile
from PIL import Image, ImageDraw

TILE_SIZE = 256
_CACHE_ROOT = Path(__file__).parent.parent / "data" / "tiles"

# In-memory feature cache: token → list of GeoJSON feature dicts.
# Populated on first tile render; cleared by invalidate_tile_cache().
_feature_cache: Dict[str, List[Dict[str, Any]]] = {}
_feature_cache_lock = threading.Lock()

_TRACK_RGBA = (249, 115, 22, 200)  # orange — matches client 0xFFF97316
_SEG_RGBA   = (136, 136, 136, 200)  # gray  — matches client 0xFF888888
_LINE_WIDTH = 3


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
    img.save(buf, format="PNG")
    return buf.getvalue()


def get_or_build_features(
    token: str,
    build: Callable[[], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Return cached features for token, or call build() to compute and cache them.

    build() is only ever called once per token (across all concurrent requests).
    A second concurrent request for the same token waits at the lock and then
    reads the value written by the first.
    """
    with _feature_cache_lock:
        if token in _feature_cache:
            return _feature_cache[token]
    # Build outside the lock so other tokens are not serialised.
    features = build()
    with _feature_cache_lock:
        # Another thread may have populated the cache while we were building.
        # Overwrite is fine — both threads computed the same result.
        _feature_cache[token] = features
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
    """Return cached PNG bytes, generating and writing to disk on first access."""
    path = _CACHE_ROOT / token / str(z) / str(x) / f"{y}.png"
    if path.exists():
        return path.read_bytes()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = render_tile(features, z, x, y)
    path.write_bytes(data)
    return data


def invalidate_tile_cache(token: str) -> None:
    """Delete all cached tiles and the in-memory feature cache for a share token."""
    d = _CACHE_ROOT / token
    if d.exists():
        shutil.rmtree(d)
    with _feature_cache_lock:
        _feature_cache.pop(token, None)
