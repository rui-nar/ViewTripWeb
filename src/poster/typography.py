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
from collections import Counter
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFont

_log = logging.getLogger(__name__)

# One scratch context for text measurement; ImageDraw.textlength needs a draw
# object but never touches these pixels.
_SCRATCH = ImageDraw.Draw(Image.new("RGB", (1, 1)))

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
    # Emoji is a *fallback* face, only consulted for characters the text face
    # has no glyph for. Text faces (Inter, DejaVu) cover no emoji at all, so
    # without one of these the U+1F300+ blocks cannot be drawn and are dropped.
    "emoji": ("NotoColorEmoji.ttf", "seguiemj.ttf", "AppleColorEmoji.ttf",
              "NotoColorEmoji-Regular.ttf", "NotoEmoji-Regular.ttf"),
}

# Emoji faces are looked for under the same names in assets/fonts/ first.
_EMOJI_CANDIDATES: Tuple[str, ...] = (
    "NotoColorEmoji.ttf",      # colour (CBDT bitmap) — the intended production face
    "NotoColorEmoji-Regular.ttf",
    "NotoEmoji-Regular.ttf",   # monochrome outline alternative
    "seguiemj.ttf",
)

# Many colour emoji fonts (Noto Color Emoji in particular) are CBDT bitmap
# fonts that only contain one fixed strike, and FreeType refuses any other
# size outright. Pillow then scales the loaded face to the requested size, so
# the file has to be opened at its native size rather than the text size.
_EMOJI_NATIVE_SIZES: Tuple[int, ...] = (109, 128, 136, 160)

_warned_default = False
_warned_no_emoji = False


def _find_face_file(weight: str) -> Optional[Path]:
    """Locate a TTF file for *weight*, or None if only the bitmap default is available."""
    names = _EMOJI_CANDIDATES if weight == "emoji" else _FACE_CANDIDATES.get(weight, ())
    for name in names:
        candidate = _ASSET_FONT_DIR / name
        if candidate.exists():
            return candidate
    for directory in _SYSTEM_FONT_DIRS:
        for name in _SYSTEM_FALLBACKS.get(weight, ()):
            candidate = directory / name
            if candidate.exists():
                return candidate
    return None


@functools.lru_cache(maxsize=64)
def load_emoji_face(size_px: int) -> Optional[Tuple[ImageFont.ImageFont, int]]:
    """Load the emoji fallback face for *size_px*, as ``(face, native_size)``.

    Returns None if no emoji font is installed. That is deliberate rather than
    an error: emoji rendering is a progressive enhancement. With no emoji face
    the stack simply has nothing covering those characters, and they are
    dropped — the previous behaviour — instead of printing .notdef boxes.

    ``native_size`` is the pixel size the face was actually opened at, which is
    not necessarily *size_px*. Colour emoji fonts are typically CBDT bitmap
    fonts carrying a single fixed strike (Noto Color Emoji has one, at 109px);
    FreeType rejects every other size with "invalid pixel size". Such a face
    must be rendered at its native strike and scaled down by the caller, so the
    size it opened at has to be reported back rather than assumed.
    """
    global _warned_no_emoji
    path = _find_face_file("emoji")
    if path is None:
        if not _warned_no_emoji:
            _warned_no_emoji = True
            _log.info(
                "No emoji face found in %s; emoji will be omitted from poster "
                "text. Drop NotoColorEmoji.ttf there to render them.",
                _ASSET_FONT_DIR,
            )
        return None

    size_px = max(1, int(size_px))
    # An outline emoji face (e.g. monochrome Noto Emoji) opens at the exact
    # size and needs no scaling; a bitmap one only opens at its strike.
    for size in (size_px, *_EMOJI_NATIVE_SIZES):
        try:
            return ImageFont.truetype(str(path), size), size
        except OSError:
            continue
    _log.warning("Found emoji face %s but could not load it at any size", path)
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
    # Semantic colour role — "primary", "muted" or "accent". The active
    # PosterTheme (see theme.py) resolves it to an actual colour at draw time;
    # ``color`` above is the unthemed fallback for anything it doesn't know.
    role: str = "primary"
    # Multiplied by the font size to get baseline-to-baseline spacing.
    line_height: float = 1.32
    # Extra space (in points) after a block in this style.
    space_after_pt: float = 0.0
    tracking_pt: float = 0.0
    uppercase: bool = False


_INK = (24, 26, 30)
_MUTED = (108, 114, 124)
# The app's brand orange (kStrava in design_tokens.dart), used for the date
# label and the legend's index numbers in both themes.
_ACCENT = (252, 76, 2)

# One place to change the poster's voice. `hero_title` is deliberately much
# larger than everything else so a card has a single obvious entry point;
# `label` is small, uppercase and tracked so stat captions read as captions
# rather than competing with the values they describe.
TYPE_SCALE: Dict[str, TextStyle] = {
    "hero_title": TextStyle(16.0, "bold", _INK, line_height=1.18, space_after_pt=1.0),
    "title": TextStyle(11.0, "bold", _INK, line_height=1.22, space_after_pt=1.0),
    # "DAY 4" — the app's canonical trip day number, set like the date label
    # (small, tracked, uppercase, brand accent) but bolder and tighter, so it
    # reads as a badge sitting above the title rather than as a second date.
    "day_badge": TextStyle(6.5, "bold", _ACCENT, role="accent", line_height=1.2,
                           space_after_pt=0.5, tracking_pt=0.5, uppercase=True),
    "date": TextStyle(7.0, "medium", _ACCENT, role="accent", space_after_pt=3.0,
                      tracking_pt=0.4, uppercase=True),
    "body": TextStyle(8.0, "regular", _INK, line_height=1.42, space_after_pt=3.0),
    "label": TextStyle(6.5, "medium", _MUTED, role="muted",
                       tracking_pt=0.5, uppercase=True),
    "stat_value": TextStyle(13.0, "bold", _INK, line_height=1.1, space_after_pt=1.0),
    "legend": TextStyle(8.0, "regular", _INK, line_height=1.3),
    "legend_index": TextStyle(7.5, "bold", _ACCENT, role="accent"),
    # Drawn over a pin, so its colour is fixed rather than theme-resolved.
    "pin_index": TextStyle(8.0, "bold", (255, 255, 255), role="fixed"),
}


class TypeScale:
    """The type scale resolved to pixels for one render's DPI.

    Every size the renderer draws with comes from here, so the physical size of
    each text role is identical across the 150 DPI render, a 300 DPI render,
    and the small preview — only the pixel numbers differ.
    """

    def __init__(self, dpi: float, overrides: Optional[Dict[str, float]] = None):
        """*overrides* maps a type-scale role name to a multiplier on that
        role's ``size_pt`` alone (leaving weight/colour/role untouched), for
        the one caller that needs a single role resized without disturbing
        every other card sharing the same ``TypeScale`` instance — the
        poster's title-scale slider (``poster_renderer``'s trip-summary card),
        which must resize only "hero_title", not a memory card's."""
        self.dpi = dpi
        self._overrides = overrides or {}
        self._fonts: Dict[str, ImageFont.ImageFont] = {}
        self._stacks: Dict[str, "FontStack"] = {}

    def px(self, points: float) -> int:
        """Convert *points* to device pixels at this render's DPI."""
        return max(1, round(points * self.dpi / 72.0))

    def _resolved(self, name: str) -> TextStyle:
        style = TYPE_SCALE[name]
        factor = self._overrides.get(name, 1.0)
        return style if factor == 1.0 else replace(style, size_pt=style.size_pt * factor)

    def style(self, name: str) -> TextStyle:
        return self._resolved(name)

    def font(self, name: str) -> ImageFont.ImageFont:
        if name not in self._fonts:
            style = self._resolved(name)
            self._fonts[name] = load_face(style.weight, self.px(style.size_pt))
        return self._fonts[name]

    def stack(self, name: str) -> "FontStack":
        """The face for *name* plus the emoji fallback, as one stack.

        All text measurement and drawing goes through a stack rather than a
        single face, because Pillow has no automatic font fallback: a string
        mixing Latin and emoji has to be split into runs and each run drawn
        with the face that actually covers it.
        """
        if name not in self._stacks:
            size = self.px(self._resolved(name).size_pt)
            faces = [self.font(name)]
            scales = [1.0]
            loaded = load_emoji_face(size)
            if loaded is not None:
                emoji_face, native = loaded
                faces.append(emoji_face)
                # A fixed-strike bitmap face renders at `native` px however
                # small the text is, so it has to be scaled down to sit on the
                # same line as the type.
                scales.append(size / native if native else 1.0)
            self._stacks[name] = FontStack(
                faces=tuple(faces), size_px=size, scales=tuple(scales))
        return self._stacks[name]

    def line_height(self, name: str) -> int:
        style = self._resolved(name)
        return max(1, round(self.px(style.size_pt) * style.line_height))

    def space_after(self, name: str) -> int:
        return round(self.px(TYPE_SCALE[name].space_after_pt))

    def prepare(self, name: str, text: str) -> str:
        """Apply a style's case transform."""
        return text.upper() if TYPE_SCALE[name].uppercase else text


# ── Font stacks and run segmentation ─────────────────────────────────────────
# Pillow performs no font fallback of its own: `draw.text` uses exactly the one
# face it is handed, and draws .notdef for anything that face lacks. Mixing
# Latin text with emoji therefore means doing the fallback by hand — splitting
# each string into maximal runs of characters covered by the same face, then
# measuring and drawing run by run while tracking the x advance.

@dataclass(frozen=True)
class Run:
    """A maximal slice of a string drawn with one face at one scale."""

    text: str
    face: ImageFont.ImageFont
    # Factor the rendered glyphs must be scaled by to match the text size.
    # 1.0 for ordinary text; < 1 for a fixed-strike bitmap emoji face.
    scale: float = 1.0

    @property
    def scaled(self) -> bool:
        return abs(self.scale - 1.0) > 1e-6

    @property
    def advance(self) -> float:
        return _SCRATCH.textlength(self.text, font=self.face) * self.scale


@dataclass(frozen=True)
class FontStack:
    """A primary text face plus fallback faces, tried in order."""

    faces: Tuple[ImageFont.ImageFont, ...]
    size_px: int
    # Per-face render scale, parallel to ``faces``.
    scales: Tuple[float, ...] = ()

    @property
    def primary(self) -> ImageFont.ImageFont:
        return self.faces[0]

    @property
    def has_fallback(self) -> bool:
        return len(self.faces) > 1

    def scale_for(self, index: int) -> float:
        return self.scales[index] if index < len(self.scales) else 1.0

    def face_for(self, ch: str) -> Optional[Tuple[ImageFont.ImageFont, float]]:
        """First ``(face, scale)`` covering *ch*, or None if nothing does."""
        for index, face in enumerate(self.faces):
            if covers(face, ch):
                return face, self.scale_for(index)
        return None


def covers(font: ImageFont.ImageFont, ch: str) -> bool:
    """True if *font* has a real glyph for *ch*.

    Determined by rendering: a character is NOT covered when it draws the
    face's .notdef glyph, or when it draws nothing at all. The second rule
    matters because Pillow's layout differs by platform — builds with
    Raqm/HarfBuzz (the Linux wheels) silently delete default-ignorable
    codepoints such as variation selectors and zero-width joiners, so those
    render blank rather than as .notdef. Neither contributes to a printed
    poster.

    Note that checking ``getbbox() is not None`` does not work: .notdef is
    usually a hollow box with a perfectly good bounding box.
    """
    if ch.isspace():
        return True
    if getattr(font, "getmask", None) is None:
        return True
    signature = _glyph_signature(font, ch)
    if signature is None:
        return True
    blank = _glyph_signature(font, " ")
    notdef = _notdef_signature(font)
    if notdef is None and blank is None:
        return True  # can't characterise this face; assume coverage
    return signature != notdef and signature != blank


_VS16 = chr(0xFE0F)  # variation selector-16: "render the preceding char as emoji"
_VS15 = chr(0xFE0E)  # variation selector-15: "render as plain text"
_ZWJ = chr(0x200D)   # zero-width joiner, binds emoji sequences

# Zero-width formatting characters that carry *presentation* information.
# No face has a visible glyph for them, so coverage tests reject them, but
# they must survive stripping long enough for split_runs to read them.
_PRESENTATION_MARKS = frozenset({_VS15, _VS16, _ZWJ})


def _resolve_emoji_first(
    stack: FontStack, ch: str
) -> Optional[Tuple[ImageFont.ImageFont, float]]:
    """Resolve *ch* preferring a fallback (emoji) face over the primary one."""
    for index in range(len(stack.faces) - 1, -1, -1):
        if covers(stack.faces[index], ch):
            return stack.faces[index], stack.scale_for(index)
    return None


def split_runs(text: str, stack: FontStack) -> List[Run]:
    """Split *text* into maximal runs, each drawn with one face.

    Characters no face in the stack covers are dropped: with an emoji font
    installed that leaves only genuinely unrenderable codepoints, and with none
    installed it reproduces the strip-the-emoji behaviour rather than printing
    boxes.
    """
    runs: List[Run] = []
    if not text:
        return runs

    current: List[str] = []
    current_face: Optional[ImageFont.ImageFont] = None
    current_scale = 1.0

    def flush() -> None:
        if current and current_face is not None:
            runs.append(Run("".join(current), current_face, current_scale))

    characters = list(text)
    for index, ch in enumerate(characters):
        if ch in _PRESENTATION_MARKS:
            continue  # consumed by the character it follows, below
        if ch.isspace():
            # Whitespace always belongs to the primary text face. Letting it
            # trail the run in progress would measure a space in the emoji
            # face — which is a 109px fixed strike, so a single space after an
            # emoji would be several times too wide and wrapping would be off.
            face, scale = stack.primary, stack.scale_for(0)
        else:
            # U+FE0F (variation selector-16) explicitly asks for the *emoji*
            # presentation of a character that also has a text form — ❄ vs ❄️.
            # Text faces like DejaVu carry monochrome glyphs for many of these,
            # so without this the primary face would claim them and the author's
            # requested colour presentation would be silently downgraded.
            wants_emoji = (index + 1 < len(characters)
                           and characters[index + 1] == _VS16)
            resolved = _resolve_emoji_first(stack, ch) if wants_emoji else stack.face_for(ch)
            if resolved is None:
                continue
            face, scale = resolved
        if face is not current_face:
            flush()
            current = []
            current_face = face
            current_scale = scale
        current.append(ch)

    flush()
    return runs


def measure_runs(runs: Sequence[Run]) -> float:
    """Total advance width of a sequence of runs."""
    return sum(run.advance for run in runs)


def strip_unsupported(text: str, stack_or_font) -> str:
    """Drop characters no face in the stack has a glyph for.

    Kept as the single place that decides what a face cannot print. With an
    emoji face in the stack, emoji now survive this and are rendered by
    ``split_runs``; without one, they are dropped as before rather than
    printed as .notdef boxes.

    Accepts a bare font as well as a stack so callers that genuinely have only
    one face (the legend, say) do not have to build one.

    Presentation marks (U+FE0E/U+FE0F, ZWJ) are deliberately preserved even
    though no face "covers" them: they are instructions to ``split_runs``,
    which consumes them when choosing a face and drops them from the output.
    Stripping them here would delete the very signal that makes "❄️" render as
    a colour emoji rather than DejaVu's monochrome ❄.
    """
    if not text:
        return text
    stack = (stack_or_font if isinstance(stack_or_font, FontStack)
             else FontStack(faces=(stack_or_font,), size_px=0))

    cleaned = "".join(
        ch for ch in text
        if ch.isspace() or ch in _PRESENTATION_MARKS or stack.face_for(ch) is not None
    )
    # Collapse the runs of spaces that removing characters tends to leave
    # behind, without touching newlines (paragraph structure is preserved
    # downstream).
    return "\n".join(" ".join(line.split()) for line in cleaned.split("\n"))


_GLYPH_BOX = (48, 48)


@functools.lru_cache(maxsize=4096)
def _glyph_signature(font: ImageFont.ImageFont, ch: str):
    """Rendered bitmap of *ch*, used to recognise the .notdef glyph.

    Rendered through ``ImageDraw`` rather than ``font.getmask``: the latter
    returns an ``ImagingCore``, which exposes no way to read its pixels back.
    Cached because layout re-measures the same characters many times.
    """
    try:
        img = Image.new("L", _GLYPH_BOX, 0)
        ImageDraw.Draw(img).text((2, 2), ch, font=font, fill=255)
        return img.tobytes()
    except Exception:
        return None


# Codepoints in unassigned Unicode planes: no font maps them, and — unlike the
# noncharacters and variation selectors tried previously — no text-shaping
# engine treats them as ignorable and deletes them before rendering. Several
# are probed, and the most common result wins, so one probe behaving oddly on
# some platform cannot disable stripping altogether.
_NOTDEF_PROBES = (chr(0x3FFFD), chr(0x4FFFD), chr(0x5FFFD))


@functools.lru_cache(maxsize=16)
def _notdef_signature(font: ImageFont.ImageFont):
    """What this face draws for a character it has no glyph for.

    Checking ``getbbox() is not None`` does NOT work: a face renders an
    unmapped codepoint as .notdef — usually a hollow box — which has a
    perfectly good bounding box and would be kept. Instead, render codepoints
    that cannot be mapped and remember that bitmap; any character rendering
    identically is missing from the font.

    Returns None if every probe came back blank, which means this face/engine
    draws nothing for unmapped codepoints; ``strip_unsupported``'s blank rule
    covers that case on its own.
    """
    blank = _glyph_signature(font, " ")
    signatures = [
        s for s in (_glyph_signature(font, p) for p in _NOTDEF_PROBES)
        if s is not None and s != blank
    ]
    if not signatures:
        return None
    return Counter(signatures).most_common(1)[0][0]


def wrap_paragraphs(text: str, stack: FontStack, max_width: float) -> List[str]:
    """Word-wrap *text* to *max_width*, preserving its paragraph breaks.

    Width is measured through the whole stack, so a line mixing text and emoji
    is measured with each part in the face that will actually draw it — an
    emoji measured in the text face would be badly wrong (it has no glyph for
    it) and lines would wrap in the wrong places.

    An earlier implementation called ``text.split()``, which discards every
    newline and welds separate paragraphs into one run-on block. Here each
    line of the source is wrapped independently and blank lines are kept, so a
    multi-paragraph memory description still reads as paragraphs.
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
            if not current or measure_runs(split_runs(trial, stack)) <= max_width:
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
