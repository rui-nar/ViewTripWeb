"""Real A0 poster rendering (issue #14).

Wires together the tile stitcher (``tile_stitcher.render_basemap``), the type
scale (``typography.TypeScale``), content-driven card measurement
(``card_layout.layout_card``), route-aware placement
(``card_placement.place_cards``) and per-day metrics
(``day_metrics.compute_day_metrics``) into the actual PNG/PDF poster.

Layers:
  - ``assemble_card_content`` is pure Python (no Pillow) — given the request's
    ``config`` flags, one memory dict, and its computed day metrics, it returns
    an ordered list of content blocks. Fully unit-testable.
  - ``card_layout.layout_card`` measures those blocks into positioned drawing
    ops and an exact card height.
  - ``_compose_poster_image`` turns ops, a stitched basemap and placed
    rectangles into pixels at whatever size/DPI its caller asks for.
  - ``render_poster`` (full resolution, saves PNG+PDF) and
    ``render_poster_preview`` (small/fast, returns PNG bytes) are thin callers
    of ``_compose_poster_image``.

Everything physical — type sizes, card dimensions, padding, pin radius — is
specified in points or millimetres and converted using the render's DPI, so the
preview, the 150 DPI render and a 300 DPI render are the same design at
different resolutions rather than three different-looking outputs.
"""
from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter

from models.db import get_session
from src.poster.card_layout import (
    PhotoOp,
    RuleOp,
    TextOp,
    card_width_px,
    layout_card,
    mm_to_px,
)
from src.poster.card_placement import PinSpec, Rect, place_cards
from src.poster.day_metrics import compute_day_metrics
from src.poster.route_index import RouteIndex
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
from src.poster.typography import TypeScale, strip_unsupported
from src.project.project_repo import ProjectRepo

_log = logging.getLogger(__name__)

ProgressFn = Callable[[str], None]

_repo = ProjectRepo()

# Scratch context for measuring emoji runs at their native size.
_MEASURE = ImageDraw.Draw(Image.new("RGB", (1, 1)))

# ── Resolution ────────────────────────────────────────────────────────────────
# A0 paper: 841mm x 1189mm = 33.11in x 46.81in.
_A0_SHORT_IN = 841.0 / 25.4
_A0_LONG_IN = 1189.0 / 25.4
_A0_SHORT_MM = 841.0
_A0_LONG_MM = 1189.0

# 150 DPI (~4967x7022 px) rather than a "true" 300 DPI A0 (~9933x14043,
# ~140M px): still genuinely print-quality at poster viewing distance, keeps a
# comfortable margin under tile_stitcher's tile cap, and halves the in-memory
# uncompressed canvas versus 300 DPI.
_DPI = 150.0

# Longest side (px) of the low-res layout preview.
_PREVIEW_MAX_DIMENSION = 900

# The preview fetches a real basemap, but at a deliberately small tile budget —
# it must stay fast and cheap. If the fetch fails it degrades to a flat colour
# and reports a warning rather than pretending the poster will look like that.
_PREVIEW_MAX_TILES = 24

# ── Palette ───────────────────────────────────────────────────────────────────
_CARD_BG = (255, 255, 255)
_CARD_BORDER = (214, 218, 224)
_CARD_SHADOW = (0, 0, 0, 46)
_RULE_COLOR = (222, 226, 232)

_PIN_COLOR = (188, 60, 44)
_PIN_OUTLINE = (255, 255, 255)
_LEADER_COLOR = (72, 78, 88)
_ROUTE_COLOR = (24, 46, 122)
_ROUTE_CASING = (255, 255, 255)

_MISSING_BASEMAP_COLOR = (226, 228, 231)

# ── Physical drawing metrics (mm unless stated) ───────────────────────────────
_PIN_RADIUS_MM = 1.5
_PIN_OUTLINE_MM = 0.45
_LEADER_WIDTH_MM = 0.28
_ROUTE_WIDTH_MM = 0.85
_ROUTE_CASING_MM = 1.5
_CARD_RADIUS_MM = 1.6
_CARD_BORDER_MM = 0.22
_CARD_SHADOW_OFFSET_MM = 0.7
_CARD_SHADOW_BLUR_MM = 1.1
_CARD_GUTTER_MM = 3.0
_PAGE_MARGIN_MM = 8.0
_LEGEND_GAP_MM = 2.0

_EMPTY_METRICS: Dict[str, Any] = {
    "distance_m": 0.0,
    "elevation_m": 0.0,
    "encounter_count": 0,
    "counters": [],
    "tag_pie": {},
}


class BasemapUnavailable(RuntimeError):
    """The basemap could not be fetched for a preview render."""


def _target_size(orientation: str, dpi: float = _DPI) -> Tuple[int, int]:
    """Pixel (width, height) for *orientation* at *dpi*."""
    long_px = round(_A0_LONG_IN * dpi)
    short_px = round(_A0_SHORT_IN * dpi)
    if orientation == "portrait":
        return short_px, long_px
    return long_px, short_px


def _pdf_resolution(width_px: int, orientation: str) -> float:
    """DPI to pass to ``Image.save(..., "PDF", resolution=...)`` so the saved
    PDF's physical page size is exactly A0."""
    width_in = _A0_LONG_IN if orientation == "landscape" else _A0_SHORT_IN
    return width_px / width_in


def _notify(progress: Optional[ProgressFn], stage: str) -> None:
    if progress is not None:
        progress(stage)


# ── Projection: lon/lat -> the same pixel frame render_basemap produced ──────

class _Projector:
    """Projects (lon, lat) degrees into the exact ``target_w`` x ``target_h``
    pixel frame that ``render_basemap`` crops and resizes its output to.

    Mirrors ``render_basemap``'s own math (same zoom choice, same crop-rect
    rounding) so memory pins and the route land on the basemap pixels a human
    would expect, rather than drifting from a slightly different projection.
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
        # canvas's own origin (the NW corner of tile (x_min, y_min)), not the
        # absolute world-pixel frame lonlat_to_pixel returns points in — fold
        # that origin in here so crop_left/crop_top are absolute world-pixel
        # offsets, matching project()'s px/py.
        x_min, _, y_min, _ = tile_range_for_bounds(bounds, self.zoom, tile_size)
        self.crop_left = x_min * tile_size + round(left)
        self.crop_top = y_min * tile_size + round(top)
        # round() the crop box exactly like render_basemap does before it
        # crops, or the resize scale would be a fraction of a percent off from
        # the basemap's actual crop.
        self.scale_x = target_w / (round(right) - round(left))
        self.scale_y = target_h / (round(bottom) - round(top))

    def project(self, lon: float, lat: float) -> Tuple[float, float]:
        px, py = lonlat_to_pixel(lon, lat, self.zoom, self.tile_size)
        return (px - self.crop_left) * self.scale_x, (py - self.crop_top) * self.scale_y


# ── Pure content assembly (no Pillow) ─────────────────────────────────────────

def assemble_card_content(
    config: Dict[str, bool], memory: Dict[str, Any], metrics: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Turn enabled ``config`` flags + one memory + its day metrics into an
    ordered list of content blocks for a poster card.

    Pure and Pillow-free so it's unit-testable without any image library.
    ``card_layout.layout_card`` turns the returned blocks into positioned
    drawing ops. Each block is a dict shaped ``{"kind": <str>, ...}``;
    ``kind`` determines the rest of its fields:

      - ``name`` / ``description`` / ``date``: ``{"text": str}``
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
        # The date rides along with the memory text: a dated card reads as a
        # journal entry, and it is what the overflow legend refers to.
        if memory.get("date"):
            blocks.append({"kind": "date", "text": _format_date(memory["date"])})
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


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _format_date(value: str) -> str:
    """'2026-07-14' -> '14 Jul 2026'; anything unparseable passes through."""
    parts = str(value)[:10].split("-")
    if len(parts) != 3:
        return str(value)
    try:
        year, month, day = int(parts[0]), int(parts[1]), int(parts[2])
        return f"{day} {_MONTHS[month - 1]} {year}"
    except (ValueError, IndexError):
        return str(value)


# ── Drawing ───────────────────────────────────────────────────────────────────

def _photo_resolver(user_id: str, memory_id: Any) -> Callable[[str], Optional[Path]]:
    """Map a photo uuid to its on-disk thumbnail, or None if absent."""
    try:
        from api.memories import _photo_dir
    except Exception:  # pragma: no cover - import guard for non-API contexts
        _log.warning("Could not import api.memories; poster photos disabled", exc_info=True)
        return lambda uuid: None

    photo_dir = _photo_dir(user_id, memory_id)

    def resolve(uuid: str) -> Optional[Path]:
        path = photo_dir / f"{uuid}_thumb.jpg"
        return path if path.exists() else None

    return resolve


def _project_route(project: Any, projector: _Projector) -> List[List[Tuple[float, float]]]:
    """Project every track feature into canvas pixel coordinates.

    Reuses ``api.geo``'s own server-side GeoJSON feature builder (the same data
    ``GET /api/geo/project`` serves the client) rather than reimplementing
    polyline decoding, and projects through the same ``_Projector`` used for
    pins so route and pins stay aligned.
    """
    try:
        from api.geo import _build_full_geo_features
    except Exception:
        _log.warning("Could not import api.geo; skipping route polyline", exc_info=True)
        return []

    lines: List[List[Tuple[float, float]]] = []
    for feature in _build_full_geo_features(project, encoded=False):
        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue
        lines.append([projector.project(lon, lat) for lon, lat in coords])
    return lines


def _draw_route(draw: ImageDraw.ImageDraw, lines: Sequence[Sequence[Tuple[float, float]]],
                dpi: float) -> None:
    """Draw the track as a white-cased coloured line, so it stays legible over
    both bright and dark satellite imagery."""
    casing = mm_to_px(_ROUTE_CASING_MM, dpi)
    width = mm_to_px(_ROUTE_WIDTH_MM, dpi)
    for line in lines:
        draw.line(list(line), fill=_ROUTE_CASING, width=casing, joint="curve")
    for line in lines:
        draw.line(list(line), fill=_ROUTE_COLOR, width=width, joint="curve")


def _draw_pin(draw: ImageDraw.ImageDraw, x: float, y: float, dpi: float) -> None:
    r = max(3, mm_to_px(_PIN_RADIUS_MM, dpi))
    draw.ellipse([x - r, y - r, x + r, y + r], fill=_PIN_COLOR,
                 outline=_PIN_OUTLINE, width=max(1, mm_to_px(_PIN_OUTLINE_MM, dpi)))


def _draw_leader(draw: ImageDraw.ImageDraw, x: float, y: float,
                 anchor: Tuple[float, float], dpi: float) -> None:
    draw.line([(x, y), anchor], fill=_LEADER_COLOR,
              width=max(1, mm_to_px(_LEADER_WIDTH_MM, dpi)))


def _paste_cover(canvas: Image.Image, path: Path, box: Tuple[int, int, int, int]) -> None:
    """Paste an image into *box*, centre-cropped to fill it.

    Cover rather than fit: letterboxed thumbnails of assorted aspect ratios
    make a card look broken, whereas a uniform crop keeps the grid regular.
    """
    x, y, w, h = box
    if w <= 0 or h <= 0:
        return
    try:
        with Image.open(path) as src:
            photo = src.convert("RGB")
    except Exception:
        _log.warning(
            "Could not open cover photo %s; leaving card slot blank", path, exc_info=True,
        )
        return

    src_w, src_h = photo.size
    if src_w == 0 or src_h == 0:
        return
    scale = max(w / src_w, h / src_h)
    new_size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))
    photo = photo.resize(new_size, Image.LANCZOS)
    left = (photo.width - w) // 2
    top = (photo.height - h) // 2
    canvas.paste(photo.crop((left, top, left + w, top + h)), (x, y))


def _draw_card_chrome(canvas: Image.Image, rect: Rect, dpi: float) -> None:
    """Rounded white card with a hairline border and a soft drop shadow.

    The shadow is composited through a layer only as large as the card plus its
    blur radius. Allocating a full-canvas RGBA layer per card instead would
    cost ~139MB *per card* at A0/150 DPI (and be blurred at that size), which
    is ruinous for both memory and time on a real poster.
    """
    radius = mm_to_px(_CARD_RADIUS_MM, dpi)
    offset = mm_to_px(_CARD_SHADOW_OFFSET_MM, dpi)
    blur = mm_to_px(_CARD_SHADOW_BLUR_MM, dpi)
    pad = blur * 3 + offset  # enough room for the blur to fall off to nothing

    tile_x = int(rect.left) - pad
    tile_y = int(rect.top) - pad
    tile_w = int(rect.right - rect.left) + 2 * pad
    tile_h = int(rect.bottom - rect.top) + 2 * pad

    shadow = Image.new("RGBA", (tile_w, tile_h), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle(
        [pad + offset, pad + offset, pad + offset + (rect.right - rect.left),
         pad + offset + (rect.bottom - rect.top)],
        radius=radius, fill=_CARD_SHADOW,
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))
    # alpha_composite needs the destination box fully inside the canvas; cards
    # sit within the page margin but the padded shadow tile can hang off it.
    canvas.alpha_composite(
        shadow.crop((
            max(0, -tile_x), max(0, -tile_y),
            tile_w - max(0, tile_x + tile_w - canvas.width),
            tile_h - max(0, tile_y + tile_h - canvas.height),
        )),
        (max(0, tile_x), max(0, tile_y)),
    )

    ImageDraw.Draw(canvas).rounded_rectangle(
        [rect.left, rect.top, rect.right, rect.bottom],
        radius=radius, fill=_CARD_BG, outline=_CARD_BORDER,
        width=max(1, mm_to_px(_CARD_BORDER_MM, dpi)),
    )


def _draw_scaled_run(
    canvas: Image.Image, op: TextOp, scale: TypeScale, ox: int, oy: int
) -> None:
    """Draw one emoji run, rendered at its face's native size then scaled down.

    Colour emoji fonts are CBDT bitmap fonts carrying a single fixed strike —
    Noto Color Emoji only opens at 109px — so they cannot simply be drawn at
    8pt body size. The run is rasterised at that native size onto a
    transparent tile with ``embedded_color`` (which is what actually produces
    colour rather than a monochrome mask), resized to the text size, and
    composited onto the card.

    The tile is aligned to the text's ascent so emoji sit on the same visual
    line as the type around them rather than floating above or below it.
    """
    face = op.face
    try:
        width = max(1, round(_MEASURE.textlength(op.text, font=face)))
        ascent, descent = face.getmetrics()
        height = max(1, ascent + descent)

        tile = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        ImageDraw.Draw(tile).text((0, 0), op.text, font=face, embedded_color=True)

        target_w = max(1, round(width * op.scale))
        target_h = max(1, round(height * op.scale))
        tile = tile.resize((target_w, target_h), Image.LANCZOS)

        # Sit the emoji's optical block on the text baseline: the surrounding
        # text is drawn from its ascender at op.y, so nudge down by the
        # difference between the text ascent and the scaled tile's own.
        text_ascent = scale.font(op.style).getmetrics()[0]
        dy = max(0, text_ascent - round(ascent * op.scale))
        canvas.alpha_composite(tile, (ox + op.x, oy + op.y + dy))
    except Exception:
        _log.warning("Could not draw emoji run %r", op.text, exc_info=True)


def _draw_card(canvas: Image.Image, rect: Rect, layout, scale: TypeScale) -> None:
    """Execute one card's measured layout ops at its placed position."""
    _draw_card_chrome(canvas, rect, scale.dpi)
    draw = ImageDraw.Draw(canvas)
    ox, oy = int(rect.left), int(rect.top)

    for op in layout.ops:
        if isinstance(op, TextOp):
            style = scale.style(op.style)
            if op.face is not None:
                _draw_scaled_run(canvas, op, scale, ox, oy)
            else:
                draw.text((ox + op.x, oy + op.y), op.text,
                          font=scale.font(op.style), fill=style.color)
        elif isinstance(op, PhotoOp):
            _paste_cover(canvas, op.path, (ox + op.x, oy + op.y, op.w, op.h))
        elif isinstance(op, RuleOp):
            draw.line([(ox + op.x, oy + op.y), (ox + op.x + op.w, oy + op.y)],
                      fill=_RULE_COLOR, width=1)


def _draw_legend(
    canvas: Image.Image,
    entries: List[Dict[str, Any]],
    pin_xy: Dict[Any, Tuple[float, float]],
    scale: TypeScale,
    target_w: int,
    target_h: int,
) -> None:
    """Number the overflowed pins on the map and list them bottom-left.

    ``entries`` is the memory dicts, in placement order, whose card could not
    be placed (see ``card_placement.CardPlacement``).
    """
    draw = ImageDraw.Draw(canvas)
    dpi = scale.dpi
    margin = mm_to_px(_PAGE_MARGIN_MM, dpi)
    pin_r = mm_to_px(_PIN_RADIUS_MM, dpi)
    line_h = scale.line_height("legend")
    gap = mm_to_px(_LEGEND_GAP_MM, dpi)
    font = scale.font("legend")
    index_font = scale.font("legend_index")
    width = card_width_px(dpi)

    box_h = len(entries) * line_h + 2 * gap
    top = max(margin, target_h - margin - box_h)
    draw.rounded_rectangle(
        [margin, top, margin + width, top + box_h],
        radius=mm_to_px(_CARD_RADIUS_MM, dpi), fill=_CARD_BG, outline=_CARD_BORDER, width=1,
    )

    y = top + gap
    for i, memory in enumerate(entries, start=1):
        px, py = pin_xy[memory["id"]]
        draw.text((px + pin_r + gap / 2, py - pin_r), str(i),
                  font=index_font, fill=scale.style("legend_index").color)
        label = memory.get("name") or _format_date(memory.get("date", ""))
        text = strip_unsupported(f"{i}. {label}", font)
        draw.text((margin + gap, y), text, font=font, fill=scale.style("legend").color)
        y += line_h


# ── Composition (shared by the full render and the low-res preview) ─────────

def _compose_poster_image(
    project_id: int,
    user_info_id: int,
    request: Dict[str, Any],
    target_w: int,
    target_h: int,
    *,
    dpi: float,
    tile_fetcher: Optional[TileFetcher] = None,
    basemap_optional: bool = False,
    max_tiles: Optional[int] = None,
    progress: Optional[ProgressFn] = None,
) -> Tuple[Image.Image, Optional[str]]:
    """Build the composited poster: basemap, route, pins, content-sized
    non-overlapping cards, and an overflow legend.

    ``dpi`` drives every physical dimension (type, card size, line widths), so
    the preview and the full render are the same design at two resolutions.

    Returns ``(image, warning)``. A basemap failure normally propagates — a
    poster without its map is not a useful output, so the job must fail with
    the underlying error rather than silently rendering on grey (issue #14
    feedback). With ``basemap_optional`` (the preview), the failure is caught
    and returned as *warning* so the client can say so plainly.
    """
    bounds = request["bounds"]
    config = request.get("config", {})
    memories: List[Dict[str, Any]] = request.get("memories", [])
    user_id = str(user_info_id)
    scale = TypeScale(dpi)
    warning: Optional[str] = None

    _notify(progress, "fetching basemap")
    kwargs = {"tile_fetcher": tile_fetcher}
    if max_tiles is not None:
        kwargs["max_tiles"] = max_tiles
    try:
        canvas = render_basemap(bounds, target_w, target_h, **kwargs)
    except Exception as exc:
        if not basemap_optional:
            raise
        _log.warning("Preview basemap unavailable: %s", exc)
        warning = f"Map imagery unavailable: {exc}"
        canvas = Image.new("RGB", (target_w, target_h), _MISSING_BASEMAP_COLOR)

    # RGBA throughout so card shadows can be alpha-composited; flattened on the
    # way out.
    canvas = canvas.convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    projector = _Projector(bounds, target_w, target_h)

    _notify(progress, "loading project")
    with get_session() as sess:
        project = _repo.get_project_by_id(sess, project_id)

    route_lines: List[List[Tuple[float, float]]] = []
    if project is not None:
        _notify(progress, "plotting route")
        route_lines = _project_route(project, projector)
        _draw_route(draw, route_lines, dpi)
    route = RouteIndex(route_lines, (target_w, target_h))

    _notify(progress, "measuring cards")
    width = card_width_px(dpi)
    pin_xy: Dict[Any, Tuple[float, float]] = {}
    layouts: Dict[Any, Any] = {}
    pins: List[PinSpec] = []
    for memory in memories:
        x, y = projector.project(memory["lon"], memory["lat"])
        pin_xy[memory["id"]] = (x, y)
        metrics = compute_day_metrics(project, memory["date"]) if project is not None else _EMPTY_METRICS
        blocks = assemble_card_content(config, memory, metrics)
        layout = layout_card(
            blocks, scale, width=width,
            photo_path=_photo_resolver(user_id, memory["id"]),
        )
        layouts[memory["id"]] = layout
        pins.append(PinSpec(id=memory["id"], x=x, y=y,
                            sort_key=memory.get("date", ""),
                            size=(layout.width, layout.height)))

    _notify(progress, "placing cards")
    placements = place_cards(
        pins, (target_w, target_h), route=route,
        margin=mm_to_px(_PAGE_MARGIN_MM, dpi),
        gutter=mm_to_px(_CARD_GUTTER_MM, dpi),
    )

    _notify(progress, "rendering cards")
    memories_by_id = {m["id"]: m for m in memories}
    legend_entries: List[Dict[str, Any]] = []

    for placement in placements:
        memory = memories_by_id.get(placement.pin_id)
        if memory is None:
            continue
        if placement.placed and placement.card_rect is not None:
            _draw_leader(draw, *pin_xy[placement.pin_id], placement.anchor, dpi)
            _draw_card(canvas, placement.card_rect, layouts[placement.pin_id], scale)
        else:
            legend_entries.append(memory)

    # Pins last, so a leader line never runs over the pin it points from.
    for pin_id, (x, y) in pin_xy.items():
        _draw_pin(ImageDraw.Draw(canvas), x, y, dpi)

    if legend_entries:
        _draw_legend(canvas, legend_entries, pin_xy, scale, target_w, target_h)

    return canvas.convert("RGB"), warning


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
    rather than a live ``DBPosterJob`` row: ``poster_job_runner`` only holds
    that row inside a short ``get_session()`` block, and this render can take a
    while (tile fetching, compositing) — it must not hold a DB session open for
    that whole duration, so it opens its own short-lived session only where it
    needs one.

    ``progress`` is called with a short stage label at each major step, for
    ``poster_job_runner`` to persist onto ``job.stage``. ``tile_fetcher`` is
    forwarded to ``render_basemap``; production leaves it ``None`` (real Mapbox
    tiles), tests inject a fake to avoid network calls.
    """
    orientation = request.get("orientation", "landscape")
    target_w, target_h = _target_size(orientation)

    canvas, _ = _compose_poster_image(
        project_id, user_info_id, request, target_w, target_h,
        dpi=_DPI, tile_fetcher=tile_fetcher, basemap_optional=False, progress=progress,
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
    tile_fetcher: Optional[TileFetcher] = None,
) -> Tuple[bytes, Optional[str]]:
    """Fast, low-resolution preview of the real poster.

    Same basemap, type scale, card measurement and placement as the full
    render, just at a small size — so what the preview shows is what the poster
    will look like, only smaller. Previously this always skipped the basemap
    and painted flat grey, which is why the map "looked grey" no matter what
    the token or network were doing.

    The tile budget is deliberately tiny (``_PREVIEW_MAX_TILES``), so the
    preview stays sub-second and cheap; at preview size the chosen zoom needs
    only a handful of tiles anyway. If the basemap can't be fetched, the
    preview still renders (on flat grey) and returns a warning describing why,
    rather than failing outright or quietly implying the poster will be grey.

    Returns ``(png_bytes, warning_or_None)``.
    """
    orientation = request.get("orientation", "landscape")
    real_w, real_h = _target_size(orientation)
    ratio = max_dimension / max(real_w, real_h)
    preview_w = max(1, round(real_w * ratio))
    preview_h = max(1, round(real_h * ratio))

    canvas, warning = _compose_poster_image(
        project_id, user_info_id, request, preview_w, preview_h,
        dpi=_DPI * ratio, tile_fetcher=tile_fetcher, basemap_optional=True,
        max_tiles=_PREVIEW_MAX_TILES, progress=None,
    )
    buf = io.BytesIO()
    canvas.save(buf, "PNG")
    return buf.getvalue(), warning
