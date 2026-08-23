"""Light/dark colour tokens for the poster's chrome.

The poster's cards, legend and stat panels used to be hard-coded white with a
grey hairline. They now follow the app's own floating-card treatment — the
``SelectionStatsOverlay`` badge in ``flutter_client/lib/src/projects/map_panel.dart``,
whose colours come from ``design_tokens.dart``/``theme.dart``:

    surface @ 94% opacity, no heavy chrome, one soft shadow dropped downwards
    (``kShadow2``), slate text (slate-700/400 in light, slate-300/500 in dark).

Two things do *not* translate literally from Flutter into this module:

  - **Geometry.** Flutter's radius (12) and blur (24) are logical pixels on a
    badge roughly 240 logical px wide. A poster card is 62mm wide, so those
    numbers are carried over as *proportions* (≈0.25mm per logical px), giving
    a 3mm radius, a 6mm blur and a 2mm drop — the same visual weight at A0
    rather than the same numbers in a different unit.
  - **Type.** The badge sets its numerals in JetBrains Mono; the poster keeps
    its own print-calibrated Inter/DejaVu stack (see ``typography.py``). Only
    the *colours* are shared.

Geometry is identical in both themes, so it lives on the dataclass as defaults
rather than being repeated per theme.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

from src.poster.typography import TextStyle

RGB = Tuple[int, int, int]
RGBA = Tuple[int, int, int, int]

# The app's brand orange (``kStrava`` in design_tokens.dart). Deliberately the
# same in both themes: it is a brand colour, not a surface-dependent one.
ACCENT: RGB = (0xFC, 0x4C, 0x02)

DEFAULT_THEME = "dark"


@dataclass(frozen=True)
class PosterTheme:
    """Every colour and shadow metric the poster's chrome draws with."""

    name: str
    card_bg: RGB
    border: RGB
    primary_text: RGB
    muted_text: RGB
    divider: RGB
    shadow: RGB
    shadow_alpha: int
    # Surfaces sit at 94% over the basemap, exactly like the app's overlay.
    card_alpha: int = 240
    accent: RGB = ACCENT
    # Physical geometry (mm), shared by both themes — see the module docstring
    # for how these were derived from the Flutter widget's logical pixels.
    radius_mm: float = 3.0
    shadow_blur_mm: float = 6.0
    shadow_offset_mm: float = 2.0

    @property
    def card_fill(self) -> RGBA:
        return (*self.card_bg, self.card_alpha)

    @property
    def border_fill(self) -> RGBA:
        return (*self.border, self.card_alpha)

    @property
    def shadow_fill(self) -> RGBA:
        return (*self.shadow, self.shadow_alpha)

    def text_color(self, style: TextStyle) -> RGB:
        """The colour *style* draws in under this theme.

        Resolved by the style's semantic ``role`` rather than by its name, so
        adding a type-scale entry does not mean editing both themes. A style
        with an unknown role keeps its own literal colour.
        """
        return {
            "primary": self.primary_text,
            "muted": self.muted_text,
            "accent": self.accent,
        }.get(style.role, style.color)


LIGHT_THEME = PosterTheme(
    name="light",
    card_bg=(0xFF, 0xFF, 0xFF),
    border=(0xE2, 0xE8, 0xF0),      # slate-200: visible against imagery, quiet on paper
    primary_text=(0x33, 0x41, 0x55),  # slate-700
    muted_text=(0x94, 0xA3, 0xB8),    # slate-400
    divider=(0xE2, 0xE8, 0xF0),       # slate-200
    shadow=(0x0F, 0x22, 0x36),
    shadow_alpha=0x2E,                # kShadow2's light colour: #0F2236 @ 18%
)

DARK_THEME = PosterTheme(
    name="dark",
    card_bg=(0x1B, 0x28, 0x38),
    border=(0x2D, 0x4A, 0x6A),      # the app's own dark border token
    primary_text=(0xCB, 0xD5, 0xE1),  # slate-300
    muted_text=(0x64, 0x74, 0x8B),    # slate-500
    divider=(0x2D, 0x4A, 0x6A),
    shadow=(0x00, 0x00, 0x00),
    shadow_alpha=0x99,                # kShadow2's dark colour: black @ 60%
)

_THEMES = {LIGHT_THEME.name: LIGHT_THEME, DARK_THEME.name: DARK_THEME}


def get_theme(name: Optional[str]) -> PosterTheme:
    """The ``PosterTheme`` for *name*, defaulting to dark.

    An unknown/missing name falls back rather than raising: the renderer is
    driven by a stored request JSON that may predate this field.
    """
    return _THEMES.get(name or DEFAULT_THEME, _THEMES[DEFAULT_THEME])
