"""Font loading and the poster's typographic scale (issue #14 feedback).

Two responsibilities:

  - **Font resolution.** ``load_face`` finds a real TrueType face for a weight,
    preferring the design system's Inter if it has been dropped into
    ``assets/fonts/``, then the vendored DejaVu Sans, then a few common system
    paths. The previous renderer called ``ImageFont.load_default(size=...)``,
    which yields one weightless fallback face — no bold, no italic, no way to
    build a visual hierarchy, which is why every card read as a flat wall of
    identical text.

  - **A physical type scale.** Poster text is specified in *points* and
    converted to pixels with the render's DPI, so a given field prints at the
    same physical size whether the poster is rendered at 150 or 300 DPI, and
    whether it is the full A0 render or a small on-screen preview. Sizing type
    in raw pixels (as the old renderer did) means text silently shrinks
    relative to the page as resolution rises.

Drop ``Inter-Regular.ttf`` / ``Inter-SemiBold.ttf`` / ``Inter-Bold.ttf`` into
``assets/fonts/`` to render the poster in the app's own typeface; nothing else
needs to change.
"""
from __future__ import annotations

import functools
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont

_log = logging.getLogger(__name__)

_ASSET_FONT_DIR = Path(__file__).resolve().parents[2] / "assets" / "fonts"

# Weight name -> candidate filenames, most-preferred first. Inter is the app's
# design-system face (see flutter_client's design_tokens.dart); DejaVu Sans is
# vendored in assets/fonts/ so a fresh checkout and the Docker image both
# render identically with no system font packages installed.
_FACE_CANDIDATES: Dict[str, Tuple[str, ...]] = {
    "regular": ("Inter-Regular.ttf", "Inter_24pt-Regular.ttf", "DejaVuSans.ttf"),
    "medium": ("Inter-Medium.ttf", "Inter-SemiBold.ttf", "Inter-Regular.ttf", "DejaVuSans.ttf"),
    "bold": ("Inter-Bold.ttf", "Inter-SemiBold.ttf", "DejaVuSans-Bold.ttf"),
}

# Searched only if nothing is found in assets/fonts/ — keeps a dev machine
# without the vendored files working rather than silently dropping to the
# bitmap default.
_SYSTEM_FONT_DIRS: Tuple[Path, ...] = (
    Path("/usr/share/fonts/truetype/dejavu"),
    Path("/usr/share/fonts/truetype/inter"),
    Path("/Library/Fonts"),
    Path("C:/Windows/Fonts"),
)
_SYSTEM_FALLBACKS: Dict[str, Tuple[str, ...]] = {
    "regular": ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "segoeui.ttf", "Helvetica.ttc"),
    "medium": ("DejaVuSans.ttf", "Arial.ttf", "arial.ttf", "segoeuisb.ttf", "Helvetica.ttc"),
    "bold": ("DejaVuSans-Bold.ttf", "Arial Bold.ttf", "arialbd.ttf", "segoeuib.ttf", "Helvetica.ttc"),
}

_warned_default = False


def _find_face_file(weight: str) -> Optional[Path]:
    """Locate a TTF file for *weight*, or None if only the bitmap default is available."""
    for name in _FACE_CANDIDATES.get(weight, ()):
        candidate = _ASSET_FONT_DIR / name
        if candidate.exists():
            return candidate
    for directory in _SYSTEM_FONT_DIRS:
        for name in _SYSTEM_FALLBACKS.get(weight, ()):
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


def load_face(weight: str, size_px: int) -> ImageFont.ImageFont:
    """Load the font face for *weight* at *size_px* pixels.

    Falls back to Pillow's built-in default (once, with a warning) only if no
    TrueType face can be found at all — that path loses bold/regular contrast,
    so it is a genuine degradation worth logging rather than passing over.
    """
    global _warned_default
    size_px = max(1, int(size_px))
    path = _find_face_file(weight)
    if path is not None:
        try:
            return ImageFont.truetype(str(path), size_px)
        except OSError:
            _log.warning("Could not load font %s; falling back", path, exc_info=True)
    if not _warned_default:
        _warned_default = True
        _log.warning(
            "No TrueType face found for poster text (looked in %s and system font "
            "dirs); falling back to Pillow's default font, which has no bold "
            "weight and will render the poster's type hierarchy flat.",
            _ASSET_FONT_DIR,
        )
    return ImageFont.load_default(size=size_px)


# ── The type scale ────────────────────────────────────────────────────────────
# Sizes are in points (1pt = 1/72 inch) as they would print on the physical
# poster. The 8pt body size is the agreed reference: body copy on an A0 poster
# reads like 8pt body copy on a page, which is correct for a poster read at
# arm's length as well as from across a room for the larger styles.

@dataclass(frozen=True)
class TextStyle:
    """One entry in the poster's type scale."""

    size_pt: float
    weight: str
    color: Tuple[int, int, int]
    # Multiplied by the font size to get baseline-to-baseline spacing.
    line_height: float = 1.32
    # Extra space (in points) after a block in this style.
    space_after_pt: float = 0.0
    tracking_pt: float = 0.0
    uppercase: bool = False


_INK = (24, 26, 30)
_MUTED = (108, 114, 124)
_ACCENT = (188, 60, 44)

# One place to change the poster's voice. `hero_title` is deliberately much
# larger than everything else so a card has a single obvious entry point;
# `label` is small, uppercase and tracked so stat captions read as captions
# rather than competing with the values they describe.
TYPE_SCALE: Dict[str, TextStyle] = {
    "hero_title": TextStyle(16.0, "bold", _INK, line_height=1.18, space_after_pt=1.0),
    "title": TextStyle(11.0, "bold", _INK, line_height=1.22, space_after_pt=1.0),
    "date": TextStyle(7.0, "medium", _MUTED, space_after_pt=3.0,
                      tracking_pt=0.4, uppercase=True),
    "body": TextStyle(8.0, "regular", _INK, line_height=1.42, space_after_pt=3.0),
    "label": TextStyle(6.5, "medium", _MUTED, tracking_pt=0.5, uppercase=True),
    "stat_value": TextStyle(13.0, "bold", _INK, line_height=1.1, space_after_pt=1.0),
    "legend": TextStyle(8.0, "regular", _INK, line_height=1.3),
    "legend_index": TextStyle(7.5, "bold", _ACCENT),
    "pin_index": TextStyle(8.0, "bold", (255, 255, 255)),
}


class TypeScale:
    """The type scale resolved to pixels for one render's DPI.

    Every size the renderer draws with comes from here, so the physical size of
    each text role is identical across the 150 DPI render, a 300 DPI render,
    and the small preview — only the pixel numbers differ.
    """

    def __init__(self, dpi: float):
        self.dpi = dpi
        self._fonts: Dict[str, ImageFont.ImageFont] = {}

    def px(self, points: float) -> int:
        """Convert *points* to device pixels at this render's DPI."""
        return max(1, round(points * self.dpi / 72.0))

    def style(self, name: str) -> TextStyle:
        return TYPE_SCALE[name]

    def font(self, name: str) -> ImageFont.ImageFont:
        if name not in self._fonts:
            style = TYPE_SCALE[name]
            self._fonts[name] = load_face(style.weight, self.px(style.size_pt))
        return self._fonts[name]

    def line_height(self, name: str) -> int:
        style = TYPE_SCALE[name]
        return max(1, round(self.px(style.size_pt) * style.line_height))

    def space_after(self, name: str) -> int:
        return round(self.px(TYPE_SCALE[name].space_after_pt))

    def prepare(self, name: str, text: str) -> str:
        """Apply a style's case transform."""
        return text.upper() if TYPE_SCALE[name].uppercase else text


# ── Text shaping helpers ──────────────────────────────────────────────────────

def strip_unsupported(text: str, font: ImageFont.ImageFont) -> str:
    """Drop characters the face has no glyph for (emoji, most notably).

    Memory names and descriptions routinely contain emoji, and neither Inter
    nor DejaVu covers them — Pillow renders missing glyphs as blank boxes,
    which is what made poster cards look garbled. Removing them is better than
    printing tofu.
    """
    if not text or getattr(font, "getmask", None) is None:
        return text

    notdef = _notdef_signature(font)
    if notdef is None:  # can't tell what "missing" looks like — leave text alone
        return text

    kept = [ch for ch in text if ch.isspace() or _glyph_signature(font, ch) != notdef]
    cleaned = "".join(kept)
    # Collapse the runs of spaces that removing emoji tends to leave behind,
    # without touching newlines (paragraph structure is preserved downstream).
    return "\n".join(" ".join(line.split()) for line in cleaned.split("\n"))


_GLYPH_BOX = (48, 48)


def _glyph_signature(font: ImageFont.ImageFont, ch: str):
    """Rendered bitmap of *ch*, used to recognise the .notdef glyph.

    Rendered through ``ImageDraw`` rather than ``font.getmask``: the latter
    returns an ``ImagingCore``, which exposes no way to read its pixels back.
    """
    try:
        img = Image.new("L", _GLYPH_BOX, 0)
        ImageDraw.Draw(img).text((2, 2), ch, font=font, fill=255)
        return img.tobytes()
    except Exception:
        return None


# Codepoints no real text face maps: a noncharacter, a permanently unassigned
# point, and a variation selector. Several are probed because DejaVu (and many
# other faces) *do* map parts of the Private Use Area, so a single PUA probe
# would come back a real glyph and silently disable stripping altogether.
_NOTDEF_PROBES = ("￿", "⿠", "󠄀")


@functools.lru_cache(maxsize=16)
def _notdef_signature(font: ImageFont.ImageFont):
    """What this face draws for a character it has no glyph for.

    Checking ``getbbox() is not None`` does NOT work: a face renders an
    unmapped codepoint as .notdef — usually a hollow box — which has a
    perfectly good bounding box and would be kept. Instead, render codepoints
    that cannot be mapped and remember that bitmap; any character rendering
    identically is missing from the font.

    The probes must agree with each other and differ from a blank: a face that
    draws nothing for unmapped points gives no signal to separate "missing"
    from "space", so stripping is disabled rather than guessed at.
    """
    sigs = {_glyph_signature(font, p) for p in _NOTDEF_PROBES}
    if len(sigs) != 1:
        return None
    signature = sigs.pop()
    if signature is None or signature == _glyph_signature(font, " "):
        return None
    return signature

def wrap_paragraphs(
    text: str,
    font: ImageFont.ImageFont,
    max_width: float,
    measure,
) -> List[str]:
    """Word-wrap *text* to *max_width*, preserving its paragraph breaks.

    The old implementation called ``text.split()``, which discards every
    newline and welds separate paragraphs into one run-on block. Here each
    line of the source is wrapped independently and blank lines are kept, so
    a multi-paragraph memory description still reads as paragraphs.
    """
    lines: List[str] = []
    for paragraph in text.split("\n"):
        stripped = paragraph.strip()
        if not stripped:
            lines.append("")
            continue
        current = ""
        for word in stripped.split():
            trial = f"{current} {word}".strip()
            if not current or measure(trial, font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    # A trailing blank line adds height for nothing.
    while lines and not lines[-1]:
        lines.pop()
    return lines
