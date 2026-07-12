"""Real A0 poster rendering (issue #14, Unit E).

Wires together Unit B's Mapbox tile stitcher (``tile_stitcher.render_basemap``),
Unit C's deterministic card placement (``card_placement.place_cards``), and
Unit D's per-day metrics (``day_metrics.compute_day_metrics``) into the actual
PNG/PDF poster that ``poster_job_runner.run_poster_job`` used to fill with a
solid-grey placeholder.

Three layers:
  - ``assemble_card_content`` is pure Python (no Pillow) — given the request's
    ``config`` flags, one memory dict, and its computed day metrics, it
    returns an ordered list of content blocks. Fully unit-testable.
  - ``_compose_poster_image`` turns those blocks, a stitched (or skipped)
    basemap, and the placed card rectangles into actual pixels, at whatever
    target size/``scale`` its caller asks for.
  - ``render_poster`` (full-resolution, saves PNG+PDF to disk) and
    ``render_poster_preview`` (small/fast, returns PNG bytes, no basemap
    network fetch) are both thin callers of ``_compose_poster_image``.
"""
from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

from models.db import get_session
from src.poster.card_placement import PinSpec, Rect, place_cards
from src.poster.day_metrics import compute_day_metrics
from src.poster.tile_stitcher import (
    DEFAULT_MAX_ZOOM,
    DEFAULT_TILE_SIZE,
    TileFetcher,
    crop_rect_for_bounds,
    lonlat_to_pixel,
    render_basemap,
    tile_range_for_bounds,
    zoom_for_target_size,
)
from src.project.project_repo import ProjectRepo

_log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]

_repo = ProjectRepo()

# ── Resolution ────────────────────────────────────────────────────────────────
# A0 paper: 841mm x 1189mm = 33.11in x 46.81in.
_A0_SHORT_IN = 841.0 / 25.4
_A0_LONG_IN = 1189.0 / 25.4

# Practical default: 150 DPI (~4967x7022 px) rather than a "true" 300 DPI A0
# (~9933x14043, ~140M px). zoom_for_target_size picks tile zoom purely from
# the requested *output* pixel size, not the bbox's real-world extent, so a
# bigger target means a higher zoom and more tiles for any bbox shape — a
# 300 DPI target risks tripping tile_stitcher's max_tiles=4096 sanity cap for
# oblong or large real-world trip bounding boxes. 150 DPI is still genuinely
# print-quality (fine at normal poster viewing distance) and keeps a
# comfortable margin under that cap, while also halving the in-memory
# uncompressed RGB canvas size versus 300 DPI.
_DPI = 150.0

# Longest side (px) of the low-res layout preview (render_poster_preview) —
# small enough to render in well under a second with zero network calls.
_PREVIEW_MAX_DIMENSION = 900

_CARD_SIZE = (620, 760)  # px at _DPI (~4.1in x 5.1in) — fits a thumbnail + a few text lines
_CARD_BG = (255, 255, 255)
_CARD_BORDER = (60, 60, 60)
_CARD_PADDING = 14

_PIN_COLOR = (200, 40, 40)
_PIN_OUTLINE = (255, 255, 255)
_PIN_RADIUS = 9

_LEADER_COLOR = (120, 120, 120)
_ROUTE_COLOR = (30, 60, 200)
_ROUTE_WIDTH = 4

_FALLBACK_BASEMAP_COLOR = (230, 230, 230)  # same neutral grey as the old stub

_LEGEND_MARGIN = 40

_EMPTY_METRICS: Dict[str, Any] = {
    "distance_m": 0.0,
    "elevation_m": 0.0,
    "encounter_count": 0,
    "counters": [],
    "tag_pie": {},
}


def _target_size(orientation: str) -> Tuple[int, int]:
    """Pixel (width, height) for *orientation* at ``_DPI``."""
    long_px = round(_A0_LONG_IN * _DPI)
    short_px = round(_A0_SHORT_IN * _DPI)
    if orientation == "portrait":
        return short_px, long_px
    return long_px, short_px


def _pdf_resolution(width_px: int, orientation: str) -> float:
    """DPI to pass as ``Image.save(..., "PDF", resolution=...)`` so the saved
    PDF's physical page size is exactly A0.

    Computed from the actual rendered pixel width divided by A0's physical
    width in inches for this orientation, rather than assuming exactly
    ``_DPI`` — ``_target_size`` rounds to whole pixels, so the true ratio is a
    hair off nominal; recomputing here keeps the PDF's physical dimensions
    correct even if the rendered width ever comes from somewhere else.
    """
    width_in = _A0_LONG_IN if orientation == "landscape" else _A0_SHORT_IN
    return width_px / width_in


def _s(value: float, scale: float) -> int:
    """Scale a reference pixel constant by *scale*, floored at 1px.

    Used throughout drawing so a low-res preview (``scale`` < 1) keeps the
    same visual proportions as the real render rather than drawing
    full-size pins/borders/text onto a tiny canvas.
    """
    return max(1, round(value * scale))


def _notify(progress: Optional[ProgressFn], stage: str) -> None:
    if progress is not None:
        progress(stage)


# ── Projection: lon/lat -> the same pixel frame render_basemap produced ──────

class _Projector:
    """Projects (lon, lat) degrees into the exact ``target_w`` x ``target_h``
    pixel frame that ``render_basemap`` crops and resizes its output to.

    Mirrors ``render_basemap``'s own math (same zoom choice, same crop-rect
    rounding) so memory pins and the route line land on the same basemap
    pixels a human would expect, rather than drifting from a slightly
    different projection.
    """

    def __init__(
        self,
        bounds: Dict[str, float],
        target_w: int,
        target_h: int,
        tile_size: int = DEFAULT_TILE_SIZE,
        max_zoom: int = DEFAULT_MAX_ZOOM,
    ):
        self.tile_size = tile_size
        self.zoom = zoom_for_target_size(bounds, target_w, target_h, tile_size, max_zoom)
        left, top, right, bottom = crop_rect_for_bounds(bounds, self.zoom, tile_size)
        # crop_rect_for_bounds returns a rect relative to the stitched tile
        # canvas's own origin (the NW corner of tile (x_min, y_min)), not to
        # the absolute world-pixel frame lonlat_to_pixel returns points in —
        # fold that origin in here so self.crop_left/crop_top are absolute
        # world-pixel offsets, matching project()'s px/py.
        x_min, _, y_min, _ = tile_range_for_bounds(bounds, self.zoom, tile_size)
        origin_x = x_min * tile_size
        origin_y = y_min * tile_size
        # round() the crop box exactly like render_basemap does before it
        # crops, or the resize scale below would be a fraction of a percent
        # off from the basemap's actual crop.
        self.crop_left = origin_x + round(left)
        self.crop_top = origin_y + round(top)
        crop_w = round(right) - round(left)
        crop_h = round(bottom) - round(top)
        self.scale_x = target_w / crop_w
        self.scale_y = target_h / crop_h

    def project(self, lon: float, lat: float) -> Tuple[float, float]:
        px, py = lonlat_to_pixel(lon, lat, self.zoom, self.tile_size)
        x = (px - self.crop_left) * self.scale_x
        y = (py - self.crop_top) * self.scale_y
        return x, y


# ── Pure content assembly (no Pillow) ─────────────────────────────────────────

def assemble_card_content(
    config: Dict[str, bool], memory: Dict[str, Any], metrics: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Turn enabled ``config`` flags + one memory + its day metrics into an
    ordered list of content blocks for a poster card.

    Pure and Pillow-free so it's unit-testable without any image library. A
    separate drawing step (``_draw_card``) turns the returned blocks into
    actual ``ImageDraw`` calls. Each block is a dict shaped
    ``{"kind": <str>, ...}``; ``kind`` determines the rest of its fields:

      - ``name`` / ``description``: ``{"text": str}``
      - ``hero_photo``: ``{"uuid": str}`` (first photo only)
      - ``photos``: ``{"uuids": list[str]}`` (all photos)
      - ``distance`` / ``elevation``: ``{"value_m": float}``
      - ``counters``: ``{"items": list[{"name": str, "value": ...}]}``
      - ``tag_pie``: ``{"data": dict[str, float]}``
      - ``encounters``: ``{"count": int}``

    A field is included only when its ``config`` flag is set *and* there is
    actual content for it (e.g. ``hero_photo`` is skipped if the memory has no
    photos; ``counters``/``tag_pie`` are skipped if empty).
    """
    blocks: List[Dict[str, Any]] = []

    if config.get("memory_text"):
        if memory.get("name"):
            blocks.append({"kind": "name", "text": memory["name"]})
        if memory.get("description"):
            blocks.append({"kind": "description", "text": memory["description"]})

    photo_uuids = memory.get("photo_uuids") or []
    if config.get("hero_photo") and photo_uuids:
        blocks.append({"kind": "hero_photo", "uuid": photo_uuids[0]})
    if config.get("all_photos") and photo_uuids:
        blocks.append({"kind": "photos", "uuids": list(photo_uuids)})

    if config.get("distance"):
        blocks.append({"kind": "distance", "value_m": metrics.get("distance_m", 0.0)})
    if config.get("elevation"):
        blocks.append({"kind": "elevation", "value_m": metrics.get("elevation_m", 0.0)})
    if config.get("counters") and metrics.get("counters"):
        blocks.append({"kind": "counters", "items": metrics["counters"]})
    if config.get("tag_pie") and metrics.get("tag_pie"):
        blocks.append({"kind": "tag_pie", "data": metrics["tag_pie"]})
    if config.get("encounters"):
        blocks.append({"kind": "encounters", "count": metrics.get("encounter_count", 0)})

    return blocks


# ── Drawing helpers ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _Fonts:
    title: ImageFont.FreeTypeFont
    body: ImageFont.FreeTypeFont
    small: ImageFont.FreeTypeFont


def _load_fonts(scale: float = 1.0) -> _Fonts:
    """Load fonts for card/legend text, sized proportionally to *scale*.

    This repo doesn't bundle a TTF anywhere (no existing Pillow text-drawing
    code to match), so per the brief's guidance this falls back to Pillow's
    built-in default font rather than adding a new font asset. Pillow >= 10.1
    lets ``load_default`` take a ``size``, which still gives a legible,
    scalable-enough result at poster resolution.
    """
    return _Fonts(
        title=ImageFont.load_default(size=_s(30, scale)),
        body=ImageFont.load_default(size=_s(20, scale)),
        small=ImageFont.load_default(size=_s(16, scale)),
    )


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: float, draw: ImageDraw.ImageDraw) -> List[str]:
    words = text.split()
    lines: List[str] = []
    cur = ""
    for word in words:
        trial = f"{cur} {word}".strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def _render_basemap_safe(
    bounds: Dict[str, float], target_w: int, target_h: int, tile_fetcher: Optional[TileFetcher] = None
) -> Image.Image:
    """``render_basemap``, falling back to a solid-colour canvas on failure.

    Self-hosted deployments may not have ``MAPBOX_TOKEN`` configured, or
    Mapbox may be briefly unreachable; either raises before any tile is
    fetched (missing token) or via a network exception. Rather than failing
    the whole poster job in that case, fall back to the same neutral grey the
    original stub used — pins, the route, and cards are still useful without
    a photographic basemap underneath.
    """
    try:
        return render_basemap(bounds, target_w, target_h, tile_fetcher=tile_fetcher)
    except Exception:
        _log.warning("Poster basemap render failed; falling back to a solid background", exc_info=True)
        return Image.new("RGB", (target_w, target_h), _FALLBACK_BASEMAP_COLOR)


def _draw_route(draw: ImageDraw.ImageDraw, project: Any, projector: _Projector, scale: float = 1.0) -> bool:
    """Draw the project's track geometry onto the basemap.

    Reuses ``api.geo``'s own server-side GeoJSON feature builder (the same
    data ``GET /api/geo/project`` serves the client) rather than
    reconstructing polyline decoding here, and projects each coordinate
    through the same ``_Projector`` used for memory pins so the route and
    pins stay aligned. Returns True if anything was drawn.
    """
    try:
        from api.geo import _build_full_geo_features
    except Exception:
        _log.warning("Could not import api.geo; skipping route polyline", exc_info=True)
        return False

    drawn = False
    for feature in _build_full_geo_features(project, encoded=False):
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        points = [projector.project(lon, lat) for lon, lat in coords]
        draw.line(points, fill=_ROUTE_COLOR, width=_s(_ROUTE_WIDTH, scale), joint="curve")
        drawn = True
    return drawn


def _draw_pin(draw: ImageDraw.ImageDraw, x: float, y: float, scale: float = 1.0) -> None:
    # A floor of 1px (via the generic _s helper) isn't enough here: at small
    # scale the outline can end up as wide as the whole circle, swallowing
    # the fill entirely and leaving no visible pin at all. Pins get their own
    # higher floor so a filled dot is always visible, however small the scale.
    r = max(3, round(_PIN_RADIUS * scale))
    draw.ellipse([x - r, y - r, x + r, y + r], fill=_PIN_COLOR, outline=_PIN_OUTLINE, width=_s(2, scale))


def _draw_leader(draw: ImageDraw.ImageDraw, x: float, y: float, rect: Rect, scale: float = 1.0) -> None:
    cx = (rect.left + rect.right) / 2
    cy = (rect.top + rect.bottom) / 2
    draw.line([(x, y), (cx, cy)], fill=_LEADER_COLOR, width=_s(2, scale))


def _draw_card(
    draw: ImageDraw.ImageDraw,
    canvas: Image.Image,
    rect: Rect,
    blocks: List[Dict[str, Any]],
    fonts: _Fonts,
    user_id: str,
    memory_id: Any,
    scale: float = 1.0,
) -> None:
    """Render one card's assembled content blocks into ``rect``.

    Blocks that don't fit before the card's bottom edge are silently
    dropped (rather than overflowing the card box) — cards are a fixed size
    by design (Unit C's placement algorithm assumes so), so a memory with a
    lot of enabled fields simply shows as much as fits.
    """
    from api.memories import _photo_dir

    draw.rectangle(
        [rect.left, rect.top, rect.right, rect.bottom],
        fill=_CARD_BG, outline=_CARD_BORDER, width=_s(2, scale),
    )

    padding = _s(_CARD_PADDING, scale)
    x = rect.left + padding
    y = rect.top + padding
    max_w = (rect.right - rect.left) - 2 * padding
    bottom_limit = rect.bottom - padding

    for block in blocks:
        if y >= bottom_limit:
            break
        kind = block["kind"]

        if kind == "name":
            draw.text((x, y), block["text"], font=fonts.title, fill=(20, 20, 20))
            y += fonts.title.size + _s(6, scale)

        elif kind == "description":
            for line in _wrap_text(block["text"], fonts.body, max_w, draw):
                if y >= bottom_limit:
                    break
                draw.text((x, y), line, font=fonts.body, fill=(50, 50, 50))
                y += fonts.body.size + _s(4, scale)

        elif kind in ("hero_photo", "photos"):
            uuids = [block["uuid"]] if kind == "hero_photo" else block["uuids"]
            photo_dir = _photo_dir(user_id, memory_id)
            for uuid in uuids:
                if y >= bottom_limit:
                    break
                thumb_path = photo_dir / f"{uuid}_thumb.jpg"
                if not thumb_path.exists():
                    continue
                try:
                    thumb = Image.open(thumb_path).convert("RGB")
                except Exception:
                    continue
                thumb.thumbnail((max_w, bottom_limit - y), Image.LANCZOS)
                canvas.paste(thumb, (int(x), int(y)))
                y += thumb.height + _s(6, scale)

        elif kind == "distance":
            draw.text((x, y), f"Distance: {block['value_m'] / 1000.0:.1f} km", font=fonts.body, fill=(30, 30, 30))
            y += fonts.body.size + _s(4, scale)

        elif kind == "elevation":
            draw.text((x, y), f"Elevation: {block['value_m']:.0f} m", font=fonts.body, fill=(30, 30, 30))
            y += fonts.body.size + _s(4, scale)

        elif kind == "counters":
            for item in block["items"]:
                if y >= bottom_limit:
                    break
                draw.text((x, y), f"{item['name']}: {item['value']}", font=fonts.small, fill=(30, 30, 30))
                y += fonts.small.size + _s(3, scale)

        elif kind == "tag_pie":
            for tag, dist in sorted(block["data"].items(), key=lambda kv: -kv[1]):
                if y >= bottom_limit:
                    break
                draw.text((x, y), f"{tag}: {dist / 1000.0:.1f} km", font=fonts.small, fill=(30, 30, 30))
                y += fonts.small.size + _s(3, scale)

        elif kind == "encounters":
            draw.text((x, y), f"Encounters: {block['count']}", font=fonts.body, fill=(30, 30, 30))
            y += fonts.body.size + _s(4, scale)


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    entries: List[Dict[str, Any]],
    pin_xy: Dict[Any, Tuple[float, float]],
    fonts: _Fonts,
    target_h: int,
    scale: float = 1.0,
) -> None:
    """Number overflowed pins on the map and list them in a small legend
    in the bottom-left margin (``entries`` is memory dicts, in placement
    order, whose card overflowed — see ``card_placement.CardPlacement``)."""
    margin = _s(_LEGEND_MARGIN, scale)
    pin_r = _s(_PIN_RADIUS, scale)
    line_h = fonts.small.size + _s(6, scale)
    y = max(margin, target_h - margin - len(entries) * line_h)
    for i, memory in enumerate(entries, start=1):
        px, py = pin_xy[memory["id"]]
        draw.text((px + pin_r + 2, py - fonts.small.size), str(i), font=fonts.small, fill=(20, 20, 20))
        label = memory.get("name") or memory.get("date", "")
        draw.text((margin, y), f"{i}. {label}", font=fonts.small, fill=(20, 20, 20))
        y += line_h


# ── Composition (shared by the full render and the low-res preview) ─────────

def _compose_poster_image(
    project_id: int,
    user_info_id: int,
    request: Dict[str, Any],
    target_w: int,
    target_h: int,
    *,
    scale: float = 1.0,
    tile_fetcher: Optional[TileFetcher] = None,
    skip_basemap: bool = False,
    progress: Optional[ProgressFn] = None,
) -> Image.Image:
    """Build the composited poster image: basemap (or a flat fallback), route,
    pins, non-overlapping cards, and an overflow legend.

    ``scale`` is the ratio of this render's pixel size to the real A0 output
    (1.0 for the real render; < 1 for ``render_poster_preview``'s small, fast
    layout preview) — card size, pin/line widths, and fonts all scale with it
    so a preview keeps the same visual proportions rather than drawing
    full-size elements onto a tiny canvas. ``skip_basemap`` bypasses the
    Mapbox tile fetch entirely (used by the preview so it never depends on
    network/``MAPBOX_TOKEN`` and stays fast).
    """
    bounds = request["bounds"]
    config = request.get("config", {})
    memories: List[Dict[str, Any]] = request.get("memories", [])
    user_id = str(user_info_id)

    _notify(progress, "fetching basemap")
    if skip_basemap:
        canvas = Image.new("RGB", (target_w, target_h), _FALLBACK_BASEMAP_COLOR)
    else:
        canvas = _render_basemap_safe(bounds, target_w, target_h, tile_fetcher=tile_fetcher)
    draw = ImageDraw.Draw(canvas)
    projector = _Projector(bounds, target_w, target_h)

    _notify(progress, "loading project")
    with get_session() as sess:
        project = _repo.get_project_by_id(sess, project_id)

    if project is not None:
        _notify(progress, "plotting route")
        _draw_route(draw, project, projector, scale)

    _notify(progress, "placing cards")
    card_size = (_s(_CARD_SIZE[0], scale), _s(_CARD_SIZE[1], scale))
    pin_xy: Dict[Any, Tuple[float, float]] = {}
    pins: List[PinSpec] = []
    for memory in memories:
        x, y = projector.project(memory["lon"], memory["lat"])
        pin_xy[memory["id"]] = (x, y)
        pins.append(PinSpec(id=memory["id"], x=x, y=y, sort_key=memory.get("date", "")))
    placements = place_cards(pins, card_size, (target_w, target_h))

    _notify(progress, "rendering cards")
    memories_by_id = {m["id"]: m for m in memories}
    fonts = _load_fonts(scale)
    legend_entries: List[Dict[str, Any]] = []

    for placement in placements:
        memory = memories_by_id.get(placement.pin_id)
        if memory is None:
            continue
        x, y = pin_xy[placement.pin_id]
        _draw_pin(draw, x, y, scale)

        if placement.placed and placement.card_rect is not None:
            metrics = compute_day_metrics(project, memory["date"]) if project is not None else _EMPTY_METRICS
            blocks = assemble_card_content(config, memory, metrics)
            _draw_leader(draw, x, y, placement.card_rect, scale)
            _draw_card(draw, canvas, placement.card_rect, blocks, fonts, user_id, memory["id"], scale)
        else:
            legend_entries.append(memory)

    if legend_entries:
        _draw_legend(draw, legend_entries, pin_xy, fonts, target_h, scale)

    return canvas


# ── Entry points ───────────────────────────────────────────────────────────────

def render_poster(
    job_id: int,
    user_info_id: int,
    project_id: int,
    request: Dict[str, Any],
    poster_dir: Path,
    progress: ProgressFn,
    *,
    tile_fetcher: Optional[TileFetcher] = None,
) -> Tuple[Path, Path]:
    """Render the poster for one job and save it as PNG + PDF.

    Takes plain scalar job fields (``job_id``/``user_info_id``/``project_id``)
    rather than a live ``DBPosterJob`` row: ``poster_job_runner`` only ever
    holds that row open inside a short ``get_session()`` block (SQLAlchemy
    expires/detaches its attributes once the session closes), and this
    render can take a while (tile fetching, image compositing) — it must not
    hold a DB session open for that whole duration, so it opens its own
    short-lived session only where it actually needs one (loading the
    ``Project`` domain object below).

    ``progress`` is called with a short human-readable stage label at each
    major step, for ``poster_job_runner`` to persist onto ``job.stage`` so
    polling clients see progress. ``tile_fetcher`` is forwarded to
    ``render_basemap``; production leaves it ``None`` (real Mapbox tiles),
    tests inject a fake one to avoid network calls.
    """
    orientation = request.get("orientation", "landscape")
    target_w, target_h = _target_size(orientation)

    canvas = _compose_poster_image(
        project_id, user_info_id, request, target_w, target_h,
        scale=1.0, tile_fetcher=tile_fetcher, skip_basemap=False, progress=progress,
    )

    _notify(progress, "encoding pdf")
    png_path = poster_dir / "poster.png"
    pdf_path = poster_dir / "poster.pdf"
    canvas.save(str(png_path), "PNG")
    canvas.save(str(pdf_path), "PDF", resolution=_pdf_resolution(target_w, orientation))

    return png_path, pdf_path


def render_poster_preview(
    project_id: int,
    user_info_id: int,
    request: Dict[str, Any],
    *,
    max_dimension: int = _PREVIEW_MAX_DIMENSION,
) -> bytes:
    """Fast, low-resolution layout preview — same card-placement/content
    logic as the real render (scaled down), but always skips the Mapbox
    basemap fetch (flat fallback colour) so it returns in well under a
    second regardless of ``MAPBOX_TOKEN``/network. For checking card
    layout/overlap and which fields show before committing to the real,
    slower job — not a preview of basemap imagery.

    Synchronous (no ``DBPosterJob`` row, no background task): returns PNG
    bytes directly. ``max_dimension`` bounds the longer side of the preview
    image, preserving the real render's A0 aspect ratio for the requested
    orientation.
    """
    orientation = request.get("orientation", "landscape")
    real_w, real_h = _target_size(orientation)
    scale = max_dimension / max(real_w, real_h)
    preview_w = max(1, round(real_w * scale))
    preview_h = max(1, round(real_h * scale))

    canvas = _compose_poster_image(
        project_id, user_info_id, request, preview_w, preview_h,
        scale=scale, tile_fetcher=None, skip_basemap=True, progress=None,
    )
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue()
