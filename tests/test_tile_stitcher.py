"""Unit tests for src/poster/tile_stitcher.py (issue #14, Unit B).

Everything here runs offline: pure pixel-math is checked against
hand-verifiable reference values, and ``render_basemap`` is exercised with a
fake ``tile_fetcher`` that returns solid-colour PNG bytes instead of hitting
Mapbox. No test in this file requires MAPBOX_TOKEN or network access.
"""
from __future__ import annotations

import functools
import io
import math

import pytest
from PIL import Image

from src.exceptions.errors import APIError
from src.poster.tile_stitcher import (
    MapboxTileClient,
    crop_rect_for_bounds,
    lonlat_to_pixel,
    render_basemap,
    tile_range_for_bounds,
    zoom_for_target_size,
)

# Standard Web Mercator latitude limit (where the projected square world map
# ends) — the well-known worked example: at zoom 0 the whole world is one tile.
_MAX_MERCATOR_LAT = 85.0511
_WORLD_BOUNDS = {"north": _MAX_MERCATOR_LAT, "south": -_MAX_MERCATOR_LAT, "east": 180.0, "west": -180.0}

# Small bbox reused across tests (matches tests/test_poster_api.py's fixture bounds).
_PARIS_BOUNDS = {"north": 48.9, "south": 48.8, "east": 2.4, "west": 2.3}


def _solid_png(color=(120, 140, 160), size=(256, 256)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# lonlat_to_pixel
# ---------------------------------------------------------------------------

def test_lonlat_to_pixel_nw_corner_is_origin():
    # abs tolerance is 1e-3 px (not 1e-6): _MAX_MERCATOR_LAT is a rounded
    # approximation of the true asymptotic Mercator latitude limit, so the
    # log/tan round-trip lands a fraction of a pixel off exact 0.
    x, y = lonlat_to_pixel(-180.0, _MAX_MERCATOR_LAT, zoom=0, tile_size=256)
    assert x == pytest.approx(0.0, abs=1e-6)
    assert y == pytest.approx(0.0, abs=1e-3)


def test_lonlat_to_pixel_se_corner_is_full_world():
    x, y = lonlat_to_pixel(180.0, -_MAX_MERCATOR_LAT, zoom=0, tile_size=256)
    assert x == pytest.approx(256.0, abs=1e-6)
    assert y == pytest.approx(256.0, abs=1e-3)


def test_lonlat_to_pixel_equator_prime_meridian_is_world_center():
    x, y = lonlat_to_pixel(0.0, 0.0, zoom=0, tile_size=256)
    assert x == pytest.approx(128.0, abs=1e-6)
    assert y == pytest.approx(128.0, abs=1e-6)


def test_lonlat_to_pixel_scales_with_zoom():
    """Doubling zoom doubles the world pixel size, so a fixed point's pixel
    coordinate (measured from the same NW origin) doubles too."""
    x0, y0 = lonlat_to_pixel(90.0, 45.0, zoom=1, tile_size=256)
    x1, y1 = lonlat_to_pixel(90.0, 45.0, zoom=2, tile_size=256)
    assert x1 == pytest.approx(x0 * 2, rel=1e-9)
    assert y1 == pytest.approx(y0 * 2, rel=1e-9)


# ---------------------------------------------------------------------------
# zoom_for_target_size
# ---------------------------------------------------------------------------

def test_zoom_for_target_size_whole_world_picks_zoom_zero():
    """Whole-globe bounds at a target just under one tile's native resolution
    should pick zoom 0 (the world fits in a single tile there).

    Target is intentionally 500 rather than the tile size (512): the Mercator
    latitude limit is asymptotic, so lonlat_to_pixel's floating-point result
    for the exact edge lands a hair under 512, not exactly at it.
    """
    z = zoom_for_target_size(_WORLD_BOUNDS, target_width=500, target_height=500, tile_size=512)
    assert z == 0


def test_zoom_for_target_size_never_upscales_below_target():
    """The chosen zoom's native resolution must meet or exceed the target in
    both dimensions (never pick a zoom that would need upscaling)."""
    target_w, target_h = 800, 600
    z = zoom_for_target_size(_PARIS_BOUNDS, target_w, target_h, tile_size=256, max_zoom=22)
    x0, y0 = lonlat_to_pixel(_PARIS_BOUNDS["west"], _PARIS_BOUNDS["north"], z, 256)
    x1, y1 = lonlat_to_pixel(_PARIS_BOUNDS["east"], _PARIS_BOUNDS["south"], z, 256)
    assert abs(x1 - x0) >= target_w
    assert abs(y1 - y0) >= target_h
    # One zoom level lower must NOT be sufficient (otherwise z isn't minimal).
    if z > 0:
        x0, y0 = lonlat_to_pixel(_PARIS_BOUNDS["west"], _PARIS_BOUNDS["north"], z - 1, 256)
        x1, y1 = lonlat_to_pixel(_PARIS_BOUNDS["east"], _PARIS_BOUNDS["south"], z - 1, 256)
        assert abs(x1 - x0) < target_w or abs(y1 - y0) < target_h


def test_zoom_for_target_size_respects_max_zoom_cap():
    """A tiny bbox against a huge target size can't reach the requested
    resolution at all — zoom must clamp to max_zoom rather than search forever
    or return something out of range."""
    tiny_bounds = {"north": 48.85001, "south": 48.85000, "east": 2.35001, "west": 2.35000}
    z = zoom_for_target_size(tiny_bounds, 9933, 14043, tile_size=512, max_zoom=22)
    assert z == 22


# ---------------------------------------------------------------------------
# tile_range_for_bounds / crop_rect_for_bounds
# ---------------------------------------------------------------------------

def test_tile_range_whole_world_at_zoom_zero_is_single_tile():
    x_min, x_max, y_min, y_max = tile_range_for_bounds(_WORLD_BOUNDS, zoom=0, tile_size=256)
    assert (x_min, x_max, y_min, y_max) == (0, 0, 0, 0)


def test_tile_range_matches_independently_computed_indices():
    """Cross-check against the textbook slippy-map formulas, computed here
    independently of the implementation under test."""
    zoom = 10
    tile_size = 256

    def expected_tile(lon, lat):
        n = 2 ** zoom
        x = int((lon + 180.0) / 360.0 * n)
        lat_rad = math.radians(lat)
        y = int((1 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2 * n)
        return x, y

    exp_x_min, exp_y_min = expected_tile(_PARIS_BOUNDS["west"], _PARIS_BOUNDS["north"])
    exp_x_max, exp_y_max = expected_tile(_PARIS_BOUNDS["east"], _PARIS_BOUNDS["south"])

    x_min, x_max, y_min, y_max = tile_range_for_bounds(_PARIS_BOUNDS, zoom, tile_size)
    assert (x_min, x_max, y_min, y_max) == (exp_x_min, exp_x_max, exp_y_min, exp_y_max)


def test_crop_rect_dimensions_match_bounds_pixel_span():
    zoom = 12
    tile_size = 256
    left, top, right, bottom = crop_rect_for_bounds(_PARIS_BOUNDS, zoom, tile_size)

    x0, y0 = lonlat_to_pixel(_PARIS_BOUNDS["west"], _PARIS_BOUNDS["north"], zoom, tile_size)
    x1, y1 = lonlat_to_pixel(_PARIS_BOUNDS["east"], _PARIS_BOUNDS["south"], zoom, tile_size)
    assert (right - left) == pytest.approx(x1 - x0, abs=1e-6)
    assert (bottom - top) == pytest.approx(y1 - y0, abs=1e-6)


def test_crop_rect_is_within_stitched_canvas_bounds():
    """The crop rect must fall inside the canvas assembled from the tile range
    at the same zoom (no negative offsets, nothing past the far edge)."""
    zoom = 12
    tile_size = 256
    x_min, x_max, y_min, y_max = tile_range_for_bounds(_PARIS_BOUNDS, zoom, tile_size)
    canvas_w = (x_max - x_min + 1) * tile_size
    canvas_h = (y_max - y_min + 1) * tile_size

    left, top, right, bottom = crop_rect_for_bounds(_PARIS_BOUNDS, zoom, tile_size)
    assert 0 <= left < right <= canvas_w
    assert 0 <= top < bottom <= canvas_h


# ---------------------------------------------------------------------------
# render_basemap (fake tile_fetcher — no network)
# ---------------------------------------------------------------------------

def test_render_basemap_returns_exact_target_dimensions():
    calls = []

    def fake_fetcher(z, x, y):
        calls.append((z, x, y))
        return _solid_png(size=(256, 256))

    img = render_basemap(_PARIS_BOUNDS, target_width=800, target_height=600,
                          tile_fetcher=fake_fetcher, tile_size=256)
    assert img.size == (800, 600)
    assert len(calls) > 0


def test_render_basemap_does_not_touch_network_when_fetcher_injected(monkeypatch):
    def _boom(*a, **k):
        raise AssertionError("should not hit the network when tile_fetcher is injected")

    monkeypatch.setattr("src.poster.tile_stitcher.requests.get", _boom)

    img = render_basemap(
        _PARIS_BOUNDS, target_width=400, target_height=300,
        tile_fetcher=lambda z, x, y: _solid_png(size=(256, 256)), tile_size=256,
    )
    assert img.size == (400, 300)


def test_render_basemap_fetches_every_tile_in_computed_range():
    from src.poster.tile_stitcher import tile_range_for_bounds, zoom_for_target_size

    zoom = zoom_for_target_size(_PARIS_BOUNDS, 800, 600, tile_size=256, max_zoom=22)
    x_min, x_max, y_min, y_max = tile_range_for_bounds(_PARIS_BOUNDS, zoom, 256)
    expected_tiles = {
        (zoom, x, y) for x in range(x_min, x_max + 1) for y in range(y_min, y_max + 1)
    }

    seen = set()

    def fake_fetcher(z, x, y):
        seen.add((z, x, y))
        return _solid_png(size=(256, 256))

    render_basemap(_PARIS_BOUNDS, target_width=800, target_height=600,
                    tile_fetcher=fake_fetcher, tile_size=256)
    assert seen == expected_tiles


# ---------------------------------------------------------------------------
# Tile-count sanity cap
# ---------------------------------------------------------------------------

def test_render_basemap_realistic_a0_request_stays_under_default_cap():
    """A real A0-at-300dpi request (~9933x14043) over a France-sized bbox
    should NOT hit the tile cap: zoom_for_target_size normalizes resolution to
    the *output* size, so tile count stays on the order of ~1-2k regardless of
    the bbox's real-world extent (verified independently while designing this
    cap: Paris-sized ~0.1deg bbox needs ~2072 tiles, France-sized ~10deg bbox
    needs ~1218 tiles, at the default 512px tile size)."""
    france_bounds = {"north": 51.0, "south": 41.0, "east": 8.0, "west": -2.0}

    def fake_fetcher(z, x, y):
        return _solid_png(size=(512, 512))

    img = render_basemap(france_bounds, target_width=9933, target_height=14043,
                          tile_fetcher=fake_fetcher)
    assert img.size == (9933, 14043)


def test_render_basemap_raises_on_oblong_bounds_exceeding_tile_cap():
    """An extreme bbox that is very wide in longitude but a sliver in latitude
    forces a high zoom (to satisfy the thin dimension's resolution
    requirement) that blows up the wide dimension's tile count. This is the
    scenario the cap exists to catch (e.g. malformed bounds)."""
    oblong_bounds = {"north": 0.001, "south": -0.001, "east": 170.0, "west": -170.0}

    def fake_fetcher(z, x, y):
        return _solid_png(size=(256, 256))

    with pytest.raises(ValueError, match="exceeding the cap"):
        render_basemap(oblong_bounds, target_width=1000, target_height=1000,
                        tile_fetcher=fake_fetcher, tile_size=256)


def test_render_basemap_respects_custom_max_tiles():
    def fake_fetcher(z, x, y):
        return _solid_png(size=(256, 256))

    with pytest.raises(ValueError, match="exceeding the cap of 10"):
        render_basemap(_PARIS_BOUNDS, target_width=800, target_height=600,
                        tile_fetcher=fake_fetcher, tile_size=256, max_tiles=10)


# ---------------------------------------------------------------------------
# MapboxTileClient
# ---------------------------------------------------------------------------

def test_mapbox_tile_client_requires_token():
    with pytest.raises(APIError):
        MapboxTileClient("")


def test_mapbox_tile_client_fetch_tile_success(monkeypatch):
    class _Resp:
        status_code = 200
        content = b"fake-png-bytes"

    monkeypatch.setattr("src.poster.tile_stitcher.requests.get", lambda *a, **k: _Resp())
    client = MapboxTileClient("tok", tile_size=256)
    assert client.fetch_tile(5, 10, 12) == b"fake-png-bytes"


def test_mapbox_tile_client_retries_then_raises_on_persistent_5xx(monkeypatch):
    class _Resp:
        status_code = 503
        text = "unavailable"

    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr("src.poster.tile_stitcher.requests.get", fake_get)
    monkeypatch.setattr("src.poster.tile_stitcher.time.sleep", lambda s: None)
    client = MapboxTileClient("tok")
    with pytest.raises(APIError, match="after 3 attempts"):
        client.fetch_tile(1, 0, 0)
    assert calls["n"] == client.MAX_RETRIES


def test_mapbox_tile_client_raises_immediately_on_4xx(monkeypatch):
    class _Resp:
        status_code = 401
        text = "invalid token"

    calls = {"n": 0}

    def fake_get(*a, **k):
        calls["n"] += 1
        return _Resp()

    monkeypatch.setattr("src.poster.tile_stitcher.requests.get", fake_get)
    client = MapboxTileClient("tok")
    with pytest.raises(APIError, match="401"):
        client.fetch_tile(1, 0, 0)
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# Retina (@2x) tiles: pixel_ratio vs logical tile_size
#
# Mapbox returns `tile_size * pixel_ratio` real pixels per tile — a @2x request
# at tilesize=512 yields a 1024x1024 image. Stitching those on a `tile_size`
# stride silently overwrites three quarters of every tile, producing a
# scrambled, 2x-zoomed basemap that no longer lines up with the projected route
# and pins. These tests pin the separation of the two concepts.
# ---------------------------------------------------------------------------

def _tile_id_blue(x: int, y: int) -> int:
    """A per-tile identifying value carried in the blue channel."""
    return 40 + (x * 53 + y * 97) % 200


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


@functools.lru_cache(maxsize=None)
def _ramp_png(blue: int, px: int) -> bytes:
    """A tile with *internal structure*: red and green ramp from 0 at the
    tile's edges up to 255 at its centre, with ``blue`` identifying the tile.

    Internal structure is essential. A tile painted one flat colour cannot
    detect the stride bug at all: pasting `tile_size * pixel_ratio` px tiles on
    a `tile_size` stride still leaves the correct tile covering each slot — it
    just draws that tile's top-left quadrant blown up 2x. Flat colours look
    identical either way, so the ramps are what make the corruption visible.

    The ramp is a triangle wave rather than a sawtooth so it is continuous
    across tile seams: the only difference between a 1x and a 2x render is
    then resampling, not ringing at a hard edge.
    """
    ramp = bytes(int(255 * (2 * u if u < 0.5 else 2 * (1 - u)))
                 for u in (i / px for i in range(px)))
    red = Image.frombytes("L", (px, px), ramp * px)
    green = Image.frombytes("L", (px, px), b"".join(bytes([v]) * px for v in ramp))
    return _png_bytes(Image.merge("RGB", (red, green, Image.new("L", (px, px), blue))))


def _ramp_fetcher(tile_size: int, pixel_ratio: int):
    px = tile_size * pixel_ratio
    return lambda z, x, y: _ramp_png(_tile_id_blue(x, y), px)


def _output_xy_for_world_point(bounds, zoom, tile_size, wx, wy, target_w, target_h):
    """Map a logical world-pixel point to output-image pixel coords, mirroring
    render_basemap's crop + resize (and poster_renderer._Projector)."""
    x_min, _, y_min, _ = tile_range_for_bounds(bounds, zoom, tile_size)
    left, top, right, bottom = crop_rect_for_bounds(bounds, zoom, tile_size)
    abs_left = x_min * tile_size + left
    abs_top = y_min * tile_size + top
    ox = (wx - abs_left) * target_w / (right - left)
    oy = (wy - abs_top) * target_h / (bottom - top)
    return ox, oy


def test_render_basemap_places_each_retina_tile_at_its_geographic_position():
    """Each tile's *centre* must land at that geographic point's output
    position, showing the tile's own centre (mid-ramp, ~127/127).

    Pasting `tile_size * 2` px tiles on a `tile_size` stride draws each tile's
    top-left quadrant stretched 2x, so a tile's centre pixel would instead show
    that quadrant's own mid-ramp (~127) rather than the tile centre's peak
    (255) — which this asserts against.
    """
    tile_size = 256
    target_w, target_h = 700, 700
    zoom = zoom_for_target_size(_PARIS_BOUNDS, target_w, target_h, tile_size, 22)
    x_min, x_max, y_min, y_max = tile_range_for_bounds(_PARIS_BOUNDS, zoom, tile_size)
    assert (x_max - x_min + 1) * (y_max - y_min + 1) >= 4, "need a multi-tile range"

    img = render_basemap(
        _PARIS_BOUNDS, target_width=target_w, target_height=target_h,
        tile_fetcher=_ramp_fetcher(tile_size, 2), tile_size=tile_size, pixel_ratio=2,
    )
    pixels = img.convert("RGB").load()

    checked = 0
    for tx in range(x_min, x_max + 1):
        for ty in range(y_min, y_max + 1):
            wx = (tx + 0.5) * tile_size  # tile centre, in logical world pixels
            wy = (ty + 0.5) * tile_size
            ox, oy = _output_xy_for_world_point(
                _PARIS_BOUNDS, zoom, tile_size, wx, wy, target_w, target_h)
            if not (4 <= ox < target_w - 4 and 4 <= oy < target_h - 4):
                continue
            r, g, b = pixels[int(ox), int(oy)]
            assert b == _tile_id_blue(tx, ty), (
                f"wrong tile at ({int(ox)},{int(oy)}): expected tile ({tx},{ty})")
            assert r >= 245 and g >= 245, (
                f"tile ({tx},{ty}) centre shows ramp ({r},{g}), expected ~(255,255) "
                "- tile content is scaled wrong")
            checked += 1
    assert checked >= 2, "test asserted on too few tiles to be meaningful"


def test_render_basemap_output_identical_for_1x_and_2x_tiles():
    """The same map data at two pixel densities must render the same picture."""
    tile_size = 256
    kwargs = dict(bounds=_PARIS_BOUNDS, target_width=300, target_height=240,
                  tile_size=tile_size)
    one_x = render_basemap(**kwargs, pixel_ratio=1,
                           tile_fetcher=_ramp_fetcher(tile_size, 1))
    two_x = render_basemap(**kwargs, pixel_ratio=2,
                           tile_fetcher=_ramp_fetcher(tile_size, 2))

    a, b = one_x.convert("RGB").load(), two_x.convert("RGB").load()
    # Red/green only: the blue tile-id channel steps at every seam, and that
    # discontinuity resamples differently from a 512px than from a 256px
    # source. The ramps carry the signal that matters here.
    worst = max(
        max(abs(a[i, j][c] - b[i, j][c]) for c in (0, 1))
        for j in range(0, 240, 3) for i in range(0, 300, 3)
    )
    # A stride bug halves the ramp's slope, a >100/255 divergence.
    assert worst <= 12, f"1x and 2x renders disagree by {worst}/255"


def test_fetch_tile_requests_retina_suffix_only_for_pixel_ratio_2(monkeypatch):
    urls = []

    class _Resp:
        status_code = 200
        content = b"x"

    def fake_get(url, **k):
        urls.append(url)
        return _Resp()

    monkeypatch.setattr("src.poster.tile_stitcher.requests.get", fake_get)

    MapboxTileClient("tok", tile_size=512, pixel_ratio=2).fetch_tile(3, 4, 5)
    MapboxTileClient("tok", tile_size=512, pixel_ratio=1).fetch_tile(3, 4, 5)

    assert urls[0].endswith("/512/3/4/5@2x")
    assert urls[1].endswith("/512/3/4/5")
