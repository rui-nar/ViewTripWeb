"""Web Mercator tile math + Mapbox raster-tile stitching for poster basemaps
(issue #14, Unit B).

Two layers:
  - Pure pixel-math (no network): standard Web Mercator slippy-map tile math
    to pick a zoom level, tile index range, and crop rectangle for a
    geographic bounding box at a target output pixel size. Fully
    unit-testable without touching the network.
  - Tile fetching + stitching: a minimal Mapbox raster-tile HTTP client
    (``MapboxTileClient``) plus ``render_basemap``, which fetches every tile
    in the computed range, pastes them into a Pillow canvas, and crops/resizes
    to the exact requested size.

``render_basemap`` is the public entry point a later unit (Unit E) wires into
``src/poster/poster_job_runner.py`` in place of its solid-grey placeholder —
this module does not touch the job runner itself.
"""
from __future__ import annotations

import io
import math
import os
import time
from typing import Callable, Dict, Optional, Tuple

import requests
from PIL import Image

from src.config.settings import Config
from src.exceptions.errors import APIError

# Pillow's decompression-bomb guard (default ~89M px, ~179M before raising)
# exists to protect against maliciously crafted untrusted image files — not
# applicable here: this module only ever creates its own canvases at sizes it
# computed itself. A0 @ 300dpi (~9933x14043, ~140M px) is a legitimate target,
# and intermediate stitched-tile crops can be larger still before the final
# resize, so the check is disabled for this process.
Image.MAX_IMAGE_PIXELS = None

# ── Server-side Mapbox token config ───────────────────────────────────────────
# Mirrors api/activities.py's Strava client-id/secret pattern: env var takes
# priority over config/config.json, applied once at import time.

_cfg = Config("config/config.json")
if os.environ.get("MAPBOX_TOKEN"):
    _cfg.set("mapbox.token", os.environ["MAPBOX_TOKEN"])


def _mapbox_token() -> str:
    """Return the configured Mapbox token (env var takes priority over config file)."""
    return os.environ.get("MAPBOX_TOKEN") or _cfg.get("mapbox.token") or ""


# ── Tunables ──────────────────────────────────────────────────────────────────

DEFAULT_TILE_SIZE = 512  # Mapbox @2x retina tiles — sharper source for A0 print
DEFAULT_MAX_ZOOM = 22    # Mapbox's practical raster max zoom (matches flutter_client's kMaxMapZoom)
DEFAULT_MAX_TILES = 4096  # sanity cap — see render_basemap's docstring for reasoning

# The style used by the client's "view" satellite basemap
# (flutter_client/lib/src/projects/basemaps.dart, kMapboxViewUrl) — reused here
# so the poster's basemap visually matches the interactive map.
DEFAULT_STYLE_USERNAME = "port82"
DEFAULT_STYLE_ID = "cmot5rk5l007301sfe4g2fyqz"

# (z, x, y) -> raw tile image bytes (e.g. PNG), sized tile_size x tile_size.
TileFetcher = Callable[[int, int, int], bytes]


# ── Pure pixel math ───────────────────────────────────────────────────────────

def lonlat_to_pixel(lon: float, lat: float, zoom: int, tile_size: int = DEFAULT_TILE_SIZE) -> Tuple[float, float]:
    """Project (lon, lat) degrees to global pixel coordinates at a given zoom.

    Standard Web Mercator slippy-map projection. The whole world is
    ``tile_size * 2**zoom`` pixels square; (0, 0) is the NW corner
    (lon=-180, lat=~+85.0511, the Mercator latitude limit).
    """
    n = 2 ** zoom
    world_px = tile_size * n
    x = (lon + 180.0) / 360.0 * world_px

    lat_rad = math.radians(lat)
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * world_px
    return x, y


def zoom_for_target_size(
    bounds: Dict[str, float],
    target_width: int,
    target_height: int,
    tile_size: int = DEFAULT_TILE_SIZE,
    max_zoom: int = DEFAULT_MAX_ZOOM,
) -> int:
    """Smallest integer zoom whose native tile resolution covers *bounds* at
    >= (*target_width*, *target_height*) pixels.

    Picking the smallest sufficient zoom (rather than the highest available)
    avoids upscaling low-resolution tiles to fill a large print canvas. If
    even ``max_zoom`` doesn't reach the target (the bounding box is very
    small relative to the requested pixel size), ``max_zoom`` is returned as
    the best available resolution.
    """
    for z in range(0, max_zoom + 1):
        x0, y0 = lonlat_to_pixel(bounds["west"], bounds["north"], z, tile_size)
        x1, y1 = lonlat_to_pixel(bounds["east"], bounds["south"], z, tile_size)
        if abs(x1 - x0) >= target_width and abs(y1 - y0) >= target_height:
            return z
    return max_zoom


def tile_range_for_bounds(
    bounds: Dict[str, float],
    zoom: int,
    tile_size: int = DEFAULT_TILE_SIZE,
) -> Tuple[int, int, int, int]:
    """Return the (x_min, x_max, y_min, y_max) tile indices covering *bounds* at *zoom*.

    Indices are clamped to the valid ``[0, 2**zoom - 1]`` range. Assumes
    ``bounds["west"] < bounds["east"]`` (no antimeridian crossing) — trip
    bounding boxes are built from a single contiguous track/memory extent, so
    this holds in practice for ``api/poster.py``'s ``BoundsIn``.
    """
    n = 2 ** zoom
    x0, y0 = lonlat_to_pixel(bounds["west"], bounds["north"], zoom, tile_size)
    x1, y1 = lonlat_to_pixel(bounds["east"], bounds["south"], zoom, tile_size)

    # Subtract a tiny epsilon before floor()ing the far edge so a bound that
    # lands exactly on a tile boundary doesn't pull in an extra empty tile.
    x_min = max(0, min(int(math.floor(x0 / tile_size)), n - 1))
    x_max = max(0, min(int(math.floor((x1 - 1e-9) / tile_size)), n - 1))
    y_min = max(0, min(int(math.floor(y0 / tile_size)), n - 1))
    y_max = max(0, min(int(math.floor((y1 - 1e-9) / tile_size)), n - 1))
    return x_min, x_max, y_min, y_max


def crop_rect_for_bounds(
    bounds: Dict[str, float],
    zoom: int,
    tile_size: int = DEFAULT_TILE_SIZE,
) -> Tuple[float, float, float, float]:
    """Return the (left, top, right, bottom) pixel crop rect for *bounds*
    within the stitched-tile canvas produced by ``tile_range_for_bounds`` at
    the same *zoom*.

    The canvas's (0, 0) is the NW corner of tile ``(x_min, y_min)``; the
    returned rect is relative to that origin and sub-pixel accurate (a
    bounding box's edges rarely land exactly on a tile boundary).
    """
    x_min, _, y_min, _ = tile_range_for_bounds(bounds, zoom, tile_size)
    origin_x = x_min * tile_size
    origin_y = y_min * tile_size

    x0, y0 = lonlat_to_pixel(bounds["west"], bounds["north"], zoom, tile_size)
    x1, y1 = lonlat_to_pixel(bounds["east"], bounds["south"], zoom, tile_size)
    return x0 - origin_x, y0 - origin_y, x1 - origin_x, y1 - origin_y


# ── Tile fetching ─────────────────────────────────────────────────────────────

class MapboxTileClient:
    """Minimal HTTP client for fetching Mapbox raster tiles.

    Mirrors the general shape of ``src/api/strava_client.py``'s ``StravaAPI``
    (a class wrapping ``requests`` with basic retry handling), but tile
    fetches don't need Strava's sliding-window rate limiter — Mapbox tile
    requests aren't window-limited the same way — so this just retries
    transient (5xx / network) failures with a short exponential backoff.
    """

    MAX_RETRIES = 3

    def __init__(
        self,
        token: str,
        *,
        style_username: str = DEFAULT_STYLE_USERNAME,
        style_id: str = DEFAULT_STYLE_ID,
        tile_size: int = DEFAULT_TILE_SIZE,
        timeout: float = 15.0,
    ):
        if not token:
            raise APIError("MAPBOX_TOKEN is not configured; cannot fetch basemap tiles")
        self.token = token
        self.style_username = style_username
        self.style_id = style_id
        self.tile_size = tile_size
        self.timeout = timeout

    def fetch_tile(self, z: int, x: int, y: int) -> bytes:
        """Fetch one raster tile's raw image bytes (PNG) from Mapbox's Styles API."""
        retina = "@2x" if self.tile_size >= 512 else ""
        url = (
            f"https://api.mapbox.com/styles/v1/{self.style_username}/{self.style_id}"
            f"/tiles/{self.tile_size}/{z}/{x}/{y}{retina}"
        )
        last_error: Optional[str] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                resp = requests.get(url, params={"access_token": self.token}, timeout=self.timeout)
            except requests.RequestException as exc:
                last_error = str(exc)
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                continue

            if resp.status_code == 200:
                return resp.content
            if resp.status_code >= 500:
                last_error = f"Server error {resp.status_code}"
                if attempt < self.MAX_RETRIES - 1:
                    time.sleep(2 ** attempt)
                continue
            # 4xx (bad token, missing tile, etc.) — not retryable.
            raise APIError(f"Mapbox tile fetch failed ({resp.status_code}): {resp.text[:200]}")

        raise APIError(f"Mapbox tile fetch failed after {self.MAX_RETRIES} attempts: {last_error}")


def _default_tile_fetcher() -> TileFetcher:
    """Build the default network tile_fetcher from the configured MAPBOX_TOKEN.

    Constructed lazily — only called from inside ``render_basemap`` when no
    fetcher is injected — so importing this module and running its
    pure-math / injected-fetcher tests never requires a token or network
    access.
    """
    client = MapboxTileClient(_mapbox_token())
    return client.fetch_tile


# ── Stitching ─────────────────────────────────────────────────────────────────

def render_basemap(
    bounds: Dict[str, float],
    target_width: int,
    target_height: int,
    *,
    tile_fetcher: Optional[TileFetcher] = None,
    tile_size: int = DEFAULT_TILE_SIZE,
    max_zoom: int = DEFAULT_MAX_ZOOM,
    max_tiles: int = DEFAULT_MAX_TILES,
) -> Image.Image:
    """Render a stitched Mapbox raster basemap covering *bounds* at exactly
    (*target_width*, *target_height*) pixels.

    ``bounds`` is a dict shaped like ``api/poster.py``'s ``BoundsIn``
    (``north``/``south``/``east``/``west`` floats, in degrees). Picks the
    smallest zoom whose native resolution covers the target size (see
    ``zoom_for_target_size``), fetches every tile in the covering range via
    *tile_fetcher*, pastes them into one canvas, crops to the exact
    bounding-box rect, and resizes to the exact requested pixel size (the
    crop is at native tile resolution, which is >= the target but rarely an
    exact pixel match).

    ``tile_fetcher`` is ``(z, x, y) -> bytes`` (raw tile image bytes, e.g.
    PNG, sized ``tile_size`` x ``tile_size``) — inject a fake in tests to
    avoid real network calls; Unit E's tests can do the same. When omitted, a
    real ``MapboxTileClient`` built from the configured ``MAPBOX_TOKEN`` is
    used.

    Raises ``ValueError`` if the tile range at the chosen zoom would exceed
    *max_tiles* — a sanity guard against pathological inputs. A legitimate
    A0-sized request needs on the order of a few hundred tiles regardless of
    the bounding box's real-world size, because ``zoom_for_target_size``
    always picks resolution to match the *output* pixel size, not the bbox's
    geographic extent — but a bbox that is much wider than it is tall (or
    vice versa) can force a zoom high enough to blow up the other dimension's
    tile count, which this cap catches.
    """
    zoom = zoom_for_target_size(bounds, target_width, target_height, tile_size, max_zoom)
    x_min, x_max, y_min, y_max = tile_range_for_bounds(bounds, zoom, tile_size)
    tiles_x = x_max - x_min + 1
    tiles_y = y_max - y_min + 1
    if tiles_x * tiles_y > max_tiles:
        raise ValueError(
            f"Basemap render would fetch {tiles_x * tiles_y} tiles at zoom {zoom}, "
            f"exceeding the cap of {max_tiles}; check bounds for an unexpectedly "
            "oblong or oversized extent"
        )

    fetcher = tile_fetcher or _default_tile_fetcher()

    canvas = Image.new("RGB", (tiles_x * tile_size, tiles_y * tile_size))
    for ty in range(y_min, y_max + 1):
        for tx in range(x_min, x_max + 1):
            tile_bytes = fetcher(zoom, tx, ty)
            tile_img = Image.open(io.BytesIO(tile_bytes)).convert("RGB")
            canvas.paste(tile_img, ((tx - x_min) * tile_size, (ty - y_min) * tile_size))

    left, top, right, bottom = crop_rect_for_bounds(bounds, zoom, tile_size)
    cropped = canvas.crop((round(left), round(top), round(right), round(bottom)))
    if cropped.size != (target_width, target_height):
        cropped = cropped.resize((target_width, target_height), Image.LANCZOS)
    return cropped
