#!/usr/bin/env python
"""Derive the Android adaptive-icon foreground from the app icon.

Android's adaptive icons composite a foreground layer over a background layer
and then mask the result to whatever shape the launcher uses (circle, squircle,
rounded square...). Only the centre ~66% of the foreground is guaranteed to be
visible, so the flat, full-bleed ``assets/app_icon.png`` cannot be used as-is:
its route glyph runs edge to edge and every launcher would crop it.

This script strips the solid background colour, then re-centres the glyph inside
the safe zone on a transparent canvas. The background colour itself is supplied
separately, as ``adaptive_icon_background`` in flutter_client/pubspec.yaml.

Run after changing assets/app_icon.png:

    python scripts/make_adaptive_icon.py
    cd flutter_client && dart run flutter_launcher_icons
"""

from __future__ import annotations

import pathlib
import sys

from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "app_icon.png"
TARGET = ROOT / "assets" / "app_icon_foreground.png"

# Fraction of the canvas the glyph may occupy. Android guarantees the inner
# 66.6% of the foreground survives masking; 0.55 leaves breathing room so this
# wide glyph does not graze the mask on circular launchers. This file owns the
# inset — flutter_launcher_icons is configured with inset 0 so the glyph is not
# shrunk a second time.
SAFE_FRACTION = 0.55
# Per-channel distance below which a pixel counts as background.
TOLERANCE = 24


def main() -> int:
    if not SOURCE.exists():
        print(f"missing {SOURCE}", file=sys.stderr)
        return 1

    icon = Image.open(SOURCE).convert("RGBA")
    size = icon.size[0]
    background = icon.getpixel((0, 0))[:3]

    # Knock out the background colour.
    pixels = icon.load()
    for y in range(icon.size[1]):
        for x in range(icon.size[0]):
            r, g, b, a = pixels[x, y]
            if (
                abs(r - background[0]) <= TOLERANCE
                and abs(g - background[1]) <= TOLERANCE
                and abs(b - background[2]) <= TOLERANCE
            ):
                pixels[x, y] = (r, g, b, 0)

    glyph = icon.crop(icon.getbbox())

    # Scale the glyph to fill the safe zone, preserving aspect ratio.
    limit = int(size * SAFE_FRACTION)
    scale = min(limit / glyph.size[0], limit / glyph.size[1])
    glyph = glyph.resize(
        (max(1, round(glyph.size[0] * scale)), max(1, round(glyph.size[1] * scale))),
        Image.LANCZOS,
    )

    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(
        glyph,
        ((size - glyph.size[0]) // 2, (size - glyph.size[1]) // 2),
        glyph,
    )
    canvas.save(TARGET)
    print(f"wrote {TARGET.relative_to(ROOT)} ({size}x{size}, glyph {glyph.size})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
