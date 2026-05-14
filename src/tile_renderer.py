"""Lazy raster-tile generation for project tracks.

Tiles are rendered with Pillow and cached to disk keyed by share_token.
The cache directory is `data/tiles/{token}/{z}/{x}/{y}.png`.
Callers must invoke `invalidate_tile_cache(token)` whenever the project's
visual content changes (activities or segments added/removed/updated).
"""
from __future__ import annotations

import io
import shutil
from pathlib import Path
from typing import Any, Dict, List, Tuple

import mercantile
from PIL import Image, ImageDraw

TILE_SIZE = 256
# Resolve absolute path so the server works regardless of working directory.
_CACHE_ROOT = Path(__file__).parent.parent / "data" / "tiles"

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


def get_cached_tile(token: str, z: int, x: int, y: int) -> bytes | None:
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
    """Delete all cached tiles for a share token (call after any project mutation)."""
    d = _CACHE_ROOT / token
    if d.exists():
        shutil.rmtree(d)
