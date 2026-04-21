#!/usr/bin/env python3
"""Generate ViewTrip web icons from the design-system hexagon logo.

Outputs:
  flutter_client/web/favicon.png          32×32
  flutter_client/web/icons/Icon-192.png   192×192
  flutter_client/web/icons/Icon-512.png   512×512
  flutter_client/web/icons/Icon-maskable-192.png  192×192 (safe-zone padded)
  flutter_client/web/icons/Icon-maskable-512.png  512×512 (safe-zone padded)
"""

import math
import os
from PIL import Image, ImageDraw

# ── Design-system colours ─────────────────────────────────────────────────────
BLUE_TOP    = (59,  130, 246)   # #3B82F6
BLUE_BOT    = (30,  64,  175)   # #1E40AF
RED_ACCENT  = (220, 38,  38)    # #DC2626
WHITE       = (255, 255, 255)
TRANSPARENT = (0,   0,   0,   0)

def lerp_color(c1, c2, t):
    return tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))


DARK_BG = (13, 27, 42)  # #0D1B2A — dark theme scaffold background

def draw_logo(size: int, pad_frac: float = 0.0, bg=None) -> Image.Image:
    """Render the hexagon logo at *size*×*size* with optional safe-zone padding.

    *pad_frac* = 0.0 for regular icon, 0.10 for maskable (10 % each side).
    *bg* = background colour tuple (r,g,b) or None for transparent.
    """
    fill = (*bg, 255) if bg else TRANSPARENT
    img = Image.new("RGBA", (size, size), fill)
    draw = ImageDraw.Draw(img)

    # Available area after padding
    inner = int(size * (1 - 2 * pad_frac))
    offset = int(size * pad_frac)

    # Scale factor: design space is 0–100
    s = inner / 100.0

    def pt(x, y):
        return (offset + x * s, offset + y * s)

    # ── Hexagon vertices ──────────────────────────────────────────────────────
    hex_pts = [pt(50, 4), pt(92, 28), pt(92, 72), pt(50, 96), pt(8, 72), pt(8, 28)]

    # ── Gradient fill: render diagonal gradient then mask with hex polygon ────
    grad = Image.new("RGBA", (size, size), TRANSPARENT)
    grad_draw = ImageDraw.Draw(grad)

    # Draw gradient bands along the diagonal (top-left → bottom-right)
    steps = inner
    for i in range(steps):
        t = i / max(steps - 1, 1)
        color = lerp_color(BLUE_TOP, BLUE_BOT, t)
        # diagonal strip: lines from (offset, offset+i) and (offset+i, offset)
        x0 = offset + i
        y0 = offset
        x1 = offset
        y1 = offset + i
        grad_draw.line([(x0, y0), (x1, y1)], fill=(*color, 255), width=2)
        # also fill the far side strip to cover the whole area
        x0b = offset + i
        y0b = offset + inner - 1
        x1b = offset + inner - 1
        y1b = offset + i
        grad_draw.line([(x0b, y0b), (x1b, y1b)], fill=(*color, 255), width=2)

    # Create hex mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).polygon(hex_pts, fill=255)

    # Composite gradient through hex mask
    img.paste(grad, mask=mask)

    # ── White route polyline ──────────────────────────────────────────────────
    route = [pt(22, 74), pt(36, 62), pt(50, 68), pt(62, 48), pt(78, 40)]
    lw = max(2, int(3.2 * s))
    draw.line(route, fill=(*WHITE, 255), width=lw, joint="curve")

    # ── Red accent rectangle ──────────────────────────────────────────────────
    rx, ry = pt(47, 65)
    rw = max(2, int(6 * s))
    draw.rectangle([rx, ry, rx + rw, ry + rw], fill=(*RED_ACCENT, 255))

    return img


def save(img: Image.Image, path: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, "PNG")
    print(f"  wrote {path}  ({img.size[0]}×{img.size[1]})")


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(__file__), "..", "flutter_client", "web")

    print("Generating ViewTrip icons…")

    # favicon — 32×32, no padding
    save(draw_logo(32),  os.path.join(base, "favicon.png"))

    # Standard icons
    save(draw_logo(192), os.path.join(base, "icons", "Icon-192.png"))
    save(draw_logo(512), os.path.join(base, "icons", "Icon-512.png"))

    # Maskable icons — 10 % safe-zone padding, dark background (Android clips to shape)
    save(draw_logo(192, pad_frac=0.10, bg=DARK_BG), os.path.join(base, "icons", "Icon-maskable-192.png"))
    save(draw_logo(512, pad_frac=0.10, bg=DARK_BG), os.path.join(base, "icons", "Icon-maskable-512.png"))

    print("Done.")
