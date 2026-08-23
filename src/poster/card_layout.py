"""Content-driven layout for poster memory cards (issue #14 feedback).

The previous renderer drew cards at a hard-coded ``(620, 760)`` px and silently
dropped any block that didn't fit before the bottom edge. Every card was the
same size no matter what the user asked for, a card with one field had the same
footprint as a card with eight, and enabling an extra field could make an
earlier one disappear.

This module replaces that with a **measure pass**: ``layout_card`` turns the
content blocks for one memory into a list of positioned drawing operations plus
the exact height they occupy. Card *width* stays uniform — a poster reads as a
composition, and ragged card widths look accidental rather than designed — but
height is whatever the content needs, between a floor and a ceiling.

Measuring and drawing come from the same pass, so the two cannot disagree: the
renderer's job is reduced to executing ops it is handed. Nothing here imports
the DB, the API, or the job runner, and photo lookup is injected, so the whole
module is unit-testable with no filesystem or network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from src.poster.typography import (
    FontStack,
    TypeScale,
    measure_runs,
    split_runs,
    strip_unsupported,
    wrap_paragraphs,
)


def measure_text(text: str, stack: FontStack) -> float:
    """Width of *text* laid out through a whole font stack.

    Always stack-aware: a string containing emoji measured in the text face
    alone would be badly wrong, because that face has no glyph for them.
    """
    return measure_runs(split_runs(text, stack))


# ── Drawing operations ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class TextOp:
    x: int
    y: int
    text: str
    style: str
    # Set when this run must be drawn with a face other than the style's own
    # (the emoji fallback). ``scale`` < 1 means the face renders at a fixed
    # size larger than the text and the renderer must scale it down.
    face: Any = None
    scale: float = 1.0


@dataclass(frozen=True)
class PhotoOp:
    x: int
    y: int
    w: int
    h: int
    path: Any  # pathlib.Path, resolved by the caller-supplied photo_path fn


@dataclass(frozen=True)
class RuleOp:
    x: int
    y: int
    w: int


@dataclass
class CardLayout:
    """A fully positioned card: ops are in card-local coordinates."""

    width: int
    height: int
    ops: List[Any] = field(default_factory=list)


# ── Physical geometry ─────────────────────────────────────────────────────────
# Card metrics are specified in millimetres so a card occupies the same physical
# area on the printed A0 sheet regardless of render DPI, exactly like the type
# scale in typography.py.

CARD_WIDTH_MM = 62.0
CARD_PADDING_MM = 4.0
CARD_MAX_HEIGHT_MM = 150.0
# The type role a card's minimum height is measured from — the smallest one in
# the scale, so the floor is genuinely "one line of text" and not a disguised
# fixed size. See ``card_min_height_px``.
MIN_HEIGHT_ROLE = "label"
HERO_ASPECT = 4 / 3          # width : height of the hero image
PHOTO_GRID_COLUMNS = 3
PHOTO_GAP_MM = 1.4
RULE_GAP_MM = 2.2

# Descriptions are trimmed rather than allowed to grow a card without limit; a
# poster card is a caption, not an article.
MAX_DESCRIPTION_LINES = 7


def mm_to_px(mm: float, dpi: float) -> int:
    return max(1, round(mm * dpi / 25.4))


def card_width_px(dpi: float) -> int:
    return mm_to_px(CARD_WIDTH_MM, dpi)


def card_min_height_px(scale: TypeScale) -> int:
    """The shortest a card may be: its padding plus one line of the smallest
    text role.

    This used to be a flat ``CARD_MIN_HEIGHT_MM = 26.0``, which is about four
    lines of body copy — so a card carrying only a date was padded out to look
    like a card carrying a paragraph, and "shrink to content" only really
    applied above that floor. Deriving the floor from the layout's own metrics
    means a sparse card is actually sparse, while still guaranteeing a card
    with no content at all is a real (small) rectangle rather than a zero- or
    negative-sized one.
    """
    return 2 * mm_to_px(CARD_PADDING_MM, scale.dpi) + scale.line_height(MIN_HEIGHT_ROLE)


class _Cursor:
    """Vertical layout cursor over a card's content column."""

    def __init__(self, x: int, y: int, width: int, limit: int):
        self.x = x
        self.y = y
        self.width = width
        self.limit = limit
        self.ops: List[Any] = []

    @property
    def remaining(self) -> int:
        return self.limit - self.y

    def fits(self, height: int) -> bool:
        return self.y + height <= self.limit


def _stat_columns(blocks: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    """Extract (label, value) pairs that should render as a stat row."""
    pairs: List[Tuple[str, str]] = []
    for block in blocks:
        kind = block["kind"]
        if kind == "distance":
            pairs.append(("Distance", f"{block['value_m'] / 1000.0:,.0f} km"))
        elif kind == "elevation":
            pairs.append(("Ascent", f"{block['value_m']:,.0f} m"))
        elif kind == "encounters":
            pairs.append(("People met", f"{block['count']}"))
    return pairs


def layout_card(
    blocks: Sequence[Dict[str, Any]],
    scale: TypeScale,
    *,
    photo_path: Optional[Callable[[str], Any]] = None,
    width: Optional[int] = None,
) -> CardLayout:
    """Lay one memory's content ``blocks`` out into a card.

    Returns a ``CardLayout`` whose ``height`` is driven by the content: a card
    showing only a name is short, one with a hero photo, a description and
    several stats is tall. ``photo_path`` maps a photo uuid to a path (or None
    if it is unavailable); when omitted, photo blocks are skipped, which keeps
    layout tests free of any filesystem dependency.
    """
    dpi = scale.dpi
    width = width or card_width_px(dpi)
    pad = mm_to_px(CARD_PADDING_MM, dpi)
    inner_w = width - 2 * pad
    max_h = mm_to_px(CARD_MAX_HEIGHT_MM, dpi)

    cur = _Cursor(pad, pad, inner_w, max_h - pad)
    by_kind: Dict[str, Dict[str, Any]] = {b["kind"]: b for b in blocks}

    # ── Hero photo: full content width, cropped to a fixed aspect ────────────
    hero = by_kind.get("hero_photo")
    if hero is not None and photo_path is not None:
        path = photo_path(hero["uuid"])
        if path is not None:
            hero_h = round(inner_w / HERO_ASPECT)
            cur.ops.append(PhotoOp(cur.x, cur.y, inner_w, hero_h, path))
            cur.y += hero_h + mm_to_px(RULE_GAP_MM, dpi)

    # ── Name + date ──────────────────────────────────────────────────────────
    name = by_kind.get("name")
    if name is not None:
        # A card led by a hero image already has a strong focal point, so its
        # name is set at title size; a text-only card carries the emphasis in
        # the name itself and gets the larger hero_title.
        style = "title" if hero is not None else "hero_title"
        cur.ops.extend(_text_block(cur, name["text"], style, scale))

    date = by_kind.get("date")
    if date is not None:
        cur.ops.extend(_text_block(cur, date["text"], "date", scale))

    # ── Description ──────────────────────────────────────────────────────────
    desc = by_kind.get("description")
    if desc is not None:
        cur.ops.extend(
            _text_block(cur, desc["text"], "body", scale, max_lines=MAX_DESCRIPTION_LINES)
        )

    # ── Stats row ────────────────────────────────────────────────────────────
    stats = _stat_columns(blocks)
    if stats:
        cur.ops.extend(_stat_block(cur, stats, scale))

    # ── Counters and tag distances ───────────────────────────────────────────
    counters = by_kind.get("counters")
    if counters is not None:
        rows = [(str(item["name"]), str(item["value"])) for item in counters["items"]]
        cur.ops.extend(_rows_block(cur, rows, scale))

    tag_pie = by_kind.get("tag_pie")
    if tag_pie is not None:
        rows = [
            (tag, f"{dist / 1000.0:,.0f} km")
            for tag, dist in sorted(tag_pie["data"].items(), key=lambda kv: -kv[1])
        ]
        cur.ops.extend(_rows_block(cur, rows, scale))

    # ── Remaining photos in a uniform grid ───────────────────────────────────
    photos = by_kind.get("photos")
    if photos is not None and photo_path is not None:
        hero_uuid = hero["uuid"] if hero is not None else None
        # The hero is already shown at full width; repeating it in the grid
        # directly beneath itself looks like a mistake.
        uuids = [u for u in photos["uuids"] if u != hero_uuid]
        cur.ops.extend(_photo_grid(cur, uuids, scale, photo_path))

    height = max(cur.y + pad, card_min_height_px(scale))
    return CardLayout(width=width, height=min(height, max_h), ops=cur.ops)


def _text_block(
    cur: _Cursor,
    text: str,
    style: str,
    scale: TypeScale,
    *,
    max_lines: Optional[int] = None,
) -> List[TextOp]:
    """Wrap and position one run of text, advancing the cursor."""
    stack = scale.stack(style)
    cleaned = strip_unsupported(scale.prepare(style, text or ""), stack)
    if not cleaned.strip():
        return []

    lines = wrap_paragraphs(cleaned, stack, cur.width)
    if max_lines is not None and len(lines) > max_lines:
        lines = lines[:max_lines]
        if lines[-1]:
            lines[-1] = _ellipsize(lines[-1], stack, cur.width)

    line_h = scale.line_height(style)
    ops: List[TextOp] = []
    for line in lines:
        if not cur.fits(line_h):
            break
        if line:  # blank lines are paragraph spacing, nothing to draw
            ops.extend(_line_ops(line, stack, style, cur.x, cur.y))
        cur.y += line_h
    cur.y += scale.space_after(style)
    return ops


def _line_ops(line: str, stack: FontStack, style: str, x: int, y: int) -> List[TextOp]:
    """Turn one laid-out line into a TextOp per font run.

    A line mixing text and emoji cannot be drawn in a single call, because
    Pillow uses exactly the face it is given and has no fallback of its own.
    Each run is emitted at its own x, advancing by that run's measured width.
    """
    ops: List[TextOp] = []
    runs = split_runs(line, stack)
    if len(runs) == 1 and not runs[0].scaled:
        # Overwhelmingly the common case: plain text, one op, no per-run x.
        return [TextOp(x, y, line, style)]

    offset = 0.0
    for run in runs:
        if run.text.strip():
            ops.append(TextOp(
                round(x + offset), y, run.text, style,
                face=run.face if run.scaled else None,
                scale=run.scale,
            ))
        offset += run.advance
    return ops


def _ellipsize(line: str, stack: FontStack, max_width: float) -> str:
    """Trim *line* so it plus an ellipsis fits within *max_width*."""
    ellipsis = "…"
    if measure_text(line + ellipsis, stack) <= max_width:
        return line + ellipsis
    words = line.split()
    while words:
        words.pop()
        candidate = " ".join(words) + ellipsis
        if measure_text(candidate, stack) <= max_width:
            return candidate
    return ellipsis


def _stat_block(cur: _Cursor, stats: List[Tuple[str, str]], scale: TypeScale) -> List[Any]:
    """A hairline rule, then label-over-value stats.

    Stats are laid out side by side when they genuinely fit, and stacked as
    label/value rows when they don't. Forcing a fixed number of equal columns
    makes long values ("2,100 m" under a "PEOPLE MET" heading) spill into the
    next column and collide with its value.
    """
    ops: List[Any] = []
    gap = mm_to_px(RULE_GAP_MM, scale.dpi)
    label_h = scale.line_height("label")
    value_h = scale.line_height("stat_value")

    if not cur.fits(gap + label_h + value_h):
        return ops

    label_stack = scale.stack("label")
    value_stack = scale.stack("stat_value")
    prepared = [
        (scale.prepare("label", strip_unsupported(label, label_stack)), value)
        for label, value in stats
    ]
    # Each column must hold its own label AND its own value.
    col_gap = mm_to_px(PHOTO_GAP_MM, scale.dpi) * 2
    widths = [
        max(measure_text(label, label_stack), measure_text(value, value_stack))
        for label, value in prepared
    ]
    fits_in_a_row = sum(widths) + col_gap * (len(widths) - 1) <= cur.width

    ops.append(RuleOp(cur.x, cur.y, cur.width))
    cur.y += gap

    if fits_in_a_row:
        x = cur.x
        for (label, value), width in zip(prepared, widths):
            ops.append(TextOp(round(x), cur.y, label, "label"))
            ops.append(TextOp(round(x), cur.y + label_h, value, "stat_value"))
            x += width + col_gap
        cur.y += label_h + value_h + scale.space_after("stat_value")
    else:
        for label, value in prepared:
            if not cur.fits(label_h + value_h):
                break
            ops.append(TextOp(cur.x, cur.y, label, "label"))
            ops.append(TextOp(cur.x, cur.y + label_h, value, "stat_value"))
            cur.y += label_h + value_h
        cur.y += scale.space_after("stat_value")
    return ops


def _rows_block(cur: _Cursor, rows: List[Tuple[str, str]], scale: TypeScale) -> List[Any]:
    """Label-left / value-right rows (counters, per-tag distances)."""
    ops: List[Any] = []
    if not rows:
        return ops
    line_h = scale.line_height("body")
    label_stack = scale.stack("label")
    value_stack = scale.stack("body")
    for label, value in rows:
        if not cur.fits(line_h):
            break
        clean_label = scale.prepare("label", strip_unsupported(label, label_stack))
        ops.extend(_line_ops(clean_label, label_stack, "label", cur.x, cur.y))
        value_w = measure_text(value, value_stack)
        ops.append(TextOp(round(cur.x + cur.width - value_w), cur.y, value, "body"))
        cur.y += line_h
    cur.y += scale.space_after("body")
    return ops


def _photo_grid(
    cur: _Cursor,
    uuids: Sequence[str],
    scale: TypeScale,
    photo_path: Callable[[str], Any],
) -> List[PhotoOp]:
    """Uniform square thumbnails, left-aligned, wrapping into rows.

    Square cells (rather than each photo's own aspect ratio) keep the grid on
    a regular rhythm; the renderer centre-crops each photo to fill its cell.
    """
    ops: List[PhotoOp] = []
    paths = [(u, photo_path(u)) for u in uuids]
    paths = [(u, p) for u, p in paths if p is not None]
    if not paths:
        return ops

    gap = mm_to_px(PHOTO_GAP_MM, scale.dpi)
    cols = PHOTO_GRID_COLUMNS
    cell = (cur.width - gap * (cols - 1)) // cols

    for index, (_, path) in enumerate(paths):
        row, col = divmod(index, cols)
        y = cur.y + row * (cell + gap)
        if y + cell > cur.limit:
            break
        ops.append(PhotoOp(cur.x + col * (cell + gap), y, cell, cell, path))

    if ops:
        rows_used = (len(ops) + cols - 1) // cols
        cur.y += rows_used * (cell + gap)
    return ops
