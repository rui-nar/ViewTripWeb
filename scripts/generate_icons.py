#!/usr/bin/env python
"""Render every icon raster the apps ship, from the TraxJourney brand mark.

The mark is design concept 6c, "Feeding in": a chrome-to-crimson ribbon with
three nodes on it, fed by source bubbles — a Strava activity trace, a photo, an
encounter — and ending on the glowing crimson "you are here".

This draws the geometry with PIL rather than rasterising the SVG, because the
project has no SVG rasteriser and PIL is already a dependency. That makes this
file one of three copies of the same geometry — change all three together:

    * assets/mark.svg, assets/app_icon.svg          the design source
    * flutter_client/lib/src/core/brand_mark.dart   in-app rendering
    * this file                                    the shipped rasters

Run by hand whenever the mark changes, then regenerate the Android launcher
icons from the PNGs this writes:

    python scripts/generate_icons.py
    cd flutter_client && dart run flutter_launcher_icons

Outputs:
    flutter_client/web/favicon.png                    32   reduced glyph
    flutter_client/web/icons/Icon-{192,512}.png            mark on its tile
    flutter_client/web/icons/Icon-maskable-{192,512}.png   safe-zone padded
    assets/app_icon.png                               512  flutter_launcher_icons
                                                           source, and the PNG
                                                           Strava registration
                                                           asks for
    assets/app_icon_background.png                    512  adaptive-icon layers
    assets/app_icon_foreground.png                    512
    .../res/drawable-*dpi/launch_image.png                  cold start, pre-12
    .../res/drawable-*dpi/splash_icon.png                   cold start, 12+
"""

from __future__ import annotations

import math
import pathlib

from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEB = ROOT / "flutter_client" / "web"
ANDROID_RES = ROOT / "flutter_client" / "android" / "app" / "src" / "main" / "res"

# ── Design space ─────────────────────────────────────────────────────────────
# Every coordinate below is in the 160×160 space the mark is authored in.
CANVAS = 160.0
# PIL has no antialiased primitives, so everything is drawn large and
# downsampled with LANCZOS.
SUPERSAMPLE = 4
# Corner radius of the icon tile.
TILE_RADIUS = 35.0
# feGaussianBlur stdDeviation on the destination node — already a sigma.
GLOW_SIGMA = 4.5

# ── Palette ──────────────────────────────────────────────────────────────────
FIELD_NEAR = (0x1B, 0x2E, 0x48)
FIELD_FAR = (0x0B, 0x14, 0x20)
RIBBON_STOPS = (
    (0.0, (0x3A, 0x52, 0x6E)),
    (0.4, (0x3B, 0x82, 0xF6)),
    (1.0, (0xEF, 0x44, 0x44)),
)
FEEDER = (0x64, 0x74, 0x8B)
ACTIVITY = (0x60, 0xA5, 0xFA)
PHOTO = (0x81, 0x8C, 0xF8)
PEOPLE = (0xC0, 0x84, 0xFC)
HOLLOW = (0x0B, 0x14, 0x20)
DESTINATION = (0xEF, 0x44, 0x44)
# Flat field behind the reduced glyph, matching the dark theme's scaffold.
FAVICON_FIELD = (0x0D, 0x1B, 0x2A)
# The reduced glyph's ribbon is a flat cobalt, not the gradient.
REDUCED_RIBBON = (0x3B, 0x82, 0xF6)

# Fraction of the output an Android adaptive-icon foreground may occupy. The
# platform only guarantees the inner ~66%; 0.62 keeps the ribbon's round caps
# clear of a circular launcher's mask.
ADAPTIVE_SAFE_FRACTION = 0.62
# Maskable PWA icons keep 10% padding each side, background bleeding to the edge.
MASKABLE_SAFE_FRACTION = 0.80

DENSITIES = {
    "mdpi": 1.0,
    "hdpi": 1.5,
    "xhdpi": 2.0,
    "xxhdpi": 3.0,
    "xxxhdpi": 4.0,
}

# Pre-Android-12 cold start centres a bitmap on the window background, at the
# splash's own mark size.
LAUNCH_DP = 168

# Android 12+ ignores the window background and runs the system splash instead,
# which scales windowSplashScreenAnimatedIcon into a 288dp canvas and masks it
# to a 192dp circle. The mark's content runs corner to corner, so the design
# canvas has to fit the circle by its diagonal, not its edge:
#   132 × √2 ≈ 187 < 192.
SPLASH_ICON_DP = 288
SPLASH_ICON_CONTENT_DP = 132


# ── Curve flattening ─────────────────────────────────────────────────────────
def _cubic(p0, p1, p2, p3, steps=64):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        pts.append(
            (
                u**3 * p0[0]
                + 3 * u * u * t * p1[0]
                + 3 * u * t * t * p2[0]
                + t**3 * p3[0],
                u**3 * p0[1]
                + 3 * u * u * t * p1[1]
                + 3 * u * t * t * p2[1]
                + t**3 * p3[1],
            )
        )
    return pts


def _quad(p0, p1, p2, steps=32):
    pts = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        pts.append(
            (
                u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1],
            )
        )
    return pts


def _chain(*runs):
    """Joins flattened runs, dropping the duplicated joint points."""
    out = list(runs[0])
    for run in runs[1:]:
        out.extend(run[1:])
    return out


# The ribbon, start of the trip to now.
RIBBON = _chain(
    _cubic((14, 140), (26, 126), (32, 118), (38, 112)),
    _cubic((38, 112), (50, 102), (64, 112), (74, 104)),
    _cubic((74, 104), (86, 94), (94, 80), (102, 72)),
    _cubic((102, 72), (112, 62), (126, 56), (136, 48)),
)
RIBBON_AXIS = ((14.0, 140.0), (136.0, 48.0))


# ── Gradients ────────────────────────────────────────────────────────────────
def _mix(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _sample_stops(stops, t):
    for i in range(len(stops) - 1):
        t0, c0 = stops[i]
        t1, c1 = stops[i + 1]
        if t <= t1:
            span = t1 - t0
            return _mix(c0, c1, 0.0 if span == 0 else (t - t0) / span)
    return stops[-1][1]


# Both gradients are smooth by construction, so they are evaluated at low
# resolution in Python and scaled up rather than looped over every output pixel.
_GRADIENT_RES = 128


def _radial_field(side):
    """The tile background: radial #1B2E48 → #0B1420 at cx 0.35, cy 0.3, r 0.85."""
    lo = _GRADIENT_RES
    small = Image.new("RGB", (lo, lo))
    px = small.load()
    cx, cy, radius = 0.35 * lo, 0.30 * lo, 0.85 * lo
    for y in range(lo):
        for x in range(lo):
            t = min(1.0, math.hypot(x + 0.5 - cx, y + 0.5 - cy) / radius)
            px[x, y] = _mix(FIELD_NEAR, FIELD_FAR, t)
    return small.resize((side, side), Image.BICUBIC)


def _ribbon_gradient(side):
    """The ribbon's linear gradient, along its own start → end axis."""
    lo = _GRADIENT_RES
    small = Image.new("RGB", (lo, lo))
    px = small.load()
    (ax, ay), (bx, by) = RIBBON_AXIS
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    for y in range(lo):
        for x in range(lo):
            gx = (x + 0.5) * CANVAS / lo
            gy = (y + 0.5) * CANVAS / lo
            t = ((gx - ax) * dx + (gy - ay) * dy) / denom
            px[x, y] = _sample_stops(RIBBON_STOPS, min(1.0, max(0.0, t)))
    return small.resize((side, side), Image.BICUBIC)


# ── Pen: design coordinates onto a scaled canvas ─────────────────────────────
class _Pen:
    """Draws design-space geometry into *image*, scaled by *scale*.

    *origin* shifts the whole drawing, so an inset glyph can be re-centred
    without a second composite.
    """

    def __init__(self, image, scale, origin=(0.0, 0.0)):
        self.image = image
        self.draw = ImageDraw.Draw(image)
        self.scale = scale
        self.origin = origin

    def at(self, x, y):
        return (self.origin[0] + x * self.scale, self.origin[1] + y * self.scale)

    def stroke(self, points, colour, width):
        """A round-capped, round-joined stroke along *points*.

        Stamped as overlapping discs rather than drawn with ImageDraw.line:
        that is literally what such a stroke is (the path swept by a disc), and
        PIL's own thick-line joints leave visible notches along a curve.
        """
        r = width * self.scale / 2
        # Chord error at this spacing is r/32 — under a tenth of a pixel once
        # the supersampled canvas is downsampled.
        spacing = max(0.7, r / 4)
        px = [self.at(*p) for p in points]
        for (x0, y0), (x1, y1) in zip(px, px[1:]):
            steps = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / spacing))
            for i in range(steps + 1):
                t = i / steps
                cx, cy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                self.draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour)

    def disc(self, centre, radius, colour):
        x, y = self.at(*centre)
        r = radius * self.scale
        self.draw.ellipse([x - r, y - r, x + r, y + r], fill=colour)

    def ring(self, centre, radius, colour, stroke_width):
        """A stroked circle over the punched-out field.

        SVG straddles a stroke across the radius, so the painted outer edge sits
        at radius + width/2 and the untouched interior ends at radius - width/2.
        """
        self.disc(centre, radius + stroke_width / 2, colour)
        self.disc(centre, radius - stroke_width / 2, HOLLOW)

    def polygon(self, points, colour):
        self.draw.polygon([self.at(*p) for p in points], fill=colour)

    def half_disc_up(self, left, radius, colour):
        """Upper half-disc of *radius* sitting on *left* — a person's shoulders."""
        cx, cy = self.at(left[0] + radius, left[1])
        r = radius * self.scale
        self.draw.pieslice([cx - r, cy - r, cx + r, cy + r], 180, 360, fill=colour)

    def frame(self, box, corner, colour, stroke_width, interior):
        """A stroked rounded rectangle, straddling the way SVG's stroke does."""
        x, y, w, h = box
        half = stroke_width / 2
        self.draw.rounded_rectangle(
            [*self.at(x - half, y - half), *self.at(x + w + half, y + h + half)],
            radius=(corner + half) * self.scale,
            fill=colour,
        )
        self.draw.rounded_rectangle(
            [*self.at(x + half, y + half), *self.at(x + w - half, y + h - half)],
            radius=max(0.0, (corner - half) * self.scale),
            fill=interior,
        )


# ── The mark ─────────────────────────────────────────────────────────────────
def _draw_mark(pen: _Pen, side: int):
    """Paints the full mark. *side* is the pixel width of pen's image."""
    # Ribbon — stroked into a mask, then its gradient composited through it.
    mask = Image.new("L", (side, side), 0)
    _Pen(mask, pen.scale, pen.origin).stroke(RIBBON, 255, 5.5)
    pen.image.paste(_ribbon_gradient(side).convert("RGBA"), (0, 0), mask)
    # paste bypassed the bound draw object's buffer; re-bind before drawing more.
    pen.draw = ImageDraw.Draw(pen.image)

    # Feeder arrows: a muted stem and an accent head, one per source.
    pen.stroke(_quad((23, 94.5), (25, 102), (34, 107.2)), FEEDER, 2.4)
    pen.polygon([(34, 107.2), (27.3, 107.05), (30.1, 101.75)], ACTIVITY)
    pen.stroke(_quad((99, 120.5), (89, 116.5), (80.4, 108)), FEEDER, 2.4)
    pen.polygon([(80.4, 108), (86.7, 110.3), (82.3, 114.4)], PHOTO)
    pen.stroke(_quad((79, 53.5), (85.5, 57.5), (95.4, 66.7)), FEEDER, 2.4)
    pen.polygon([(95.4, 66.7), (89, 64.8), (93, 60.4)], PEOPLE)

    # Source bubble: a Strava activity trace.
    pen.ring((18, 88), 10, ACTIVITY, 2.6)
    pen.stroke([(13.5, 90.5), (16.5, 86), (19.5, 89), (23, 83.5)], ACTIVITY, 2)

    # Source bubble: a photo.
    pen.ring((106, 124), 10, PHOTO, 2.6)
    pen.frame((100.5, 119.5, 11, 9), 1.8, PHOTO, 2, HOLLOW)
    pen.polygon([(102.5, 127.5), (105.5, 123), (108.5, 127.5)], PHOTO)

    # Source bubble: an encounter, two people.
    pen.ring((72, 48), 11, PEOPLE, 2.6)
    pen.disc((76.2, 42.5), 1.9, PEOPLE)
    pen.half_disc_up((73.5, 47.5), 2.7, PEOPLE)
    pen.disc((69, 46.5), 2.7, PEOPLE)
    pen.half_disc_up((65.3, 53.5), 3.7, PEOPLE)

    # Plain nodes riding the ribbon.
    pen.ring((38, 112), 7, ACTIVITY, 3)
    pen.ring((74, 104), 8, PHOTO, 3)
    pen.ring((102, 72), 9, PEOPLE, 3.2)

    # "You are here", under its own glow.
    glow = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    _Pen(glow, pen.scale, pen.origin).disc((136, 48), 13, (*DESTINATION, 255))
    pen.image.alpha_composite(glow.filter(ImageFilter.GaussianBlur(GLOW_SIGMA * pen.scale)))
    pen.draw = ImageDraw.Draw(pen.image)
    pen.disc((136, 48), 13, DESTINATION)


def _draw_reduced_mark(pen: _Pen):
    """The design's small-size reduction: ribbon, encounter, destination.

    Below roughly 32 px the full mark turns to mush, so the favicon uses the
    stripped-back glyph the design board specifies for its smallest tile.
    """
    pen.stroke(RIBBON, REDUCED_RIBBON, 11)
    pen.disc((102, 72), 15, PEOPLE)
    pen.disc((136, 48), 20, DESTINATION)


# ── Compositions ─────────────────────────────────────────────────────────────
def _glyph(work, reduced=False, fraction=1.0):
    """The mark alone on transparency, filling *fraction* of a *work*-px square."""
    image = Image.new("RGBA", (work, work), (0, 0, 0, 0))
    inset = work * (1 - fraction) / 2
    pen = _Pen(image, work * fraction / CANVAS, (inset, inset))
    if reduced:
        _draw_reduced_mark(pen)
    else:
        _draw_mark(pen, work)
    return image


def _on_field(side, fraction=1.0, squircle=True, flat=None, reduced=False):
    """The mark over its field, supersampled then downsampled to *side*.

    *flat* replaces the radial gradient with a solid colour; *squircle* rounds
    the tile's corners, which maskable icons must not do.
    """
    work = side * SUPERSAMPLE
    if flat is not None:
        field = Image.new("RGBA", (work, work), (*flat, 255))
    else:
        field = _radial_field(work).convert("RGBA")

    field.alpha_composite(_glyph(work, reduced=reduced, fraction=fraction))

    if squircle:
        mask = Image.new("L", (work, work), 0)
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, work - 1, work - 1],
            radius=TILE_RADIUS * work / CANVAS,
            fill=255,
        )
        field.putalpha(mask)
    return field.resize((side, side), Image.LANCZOS)


def _save(image, path: pathlib.Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG")
    print(f"  {path.relative_to(ROOT)}  ({image.size[0]}×{image.size[1]})")


def main() -> int:
    print("Rendering the TraxJourney mark…")

    # Web: the favicon uses the reduced glyph, the PWA icons the full mark.
    _save(
        _on_field(32, flat=FAVICON_FIELD, reduced=True, squircle=False),
        WEB / "favicon.png",
    )
    _save(_on_field(192), WEB / "icons" / "Icon-192.png")
    _save(_on_field(512), WEB / "icons" / "Icon-512.png")
    # Maskable: field to the edges, glyph inside the safe zone, no rounding —
    # the launcher applies its own mask.
    _save(
        _on_field(192, fraction=MASKABLE_SAFE_FRACTION, squircle=False),
        WEB / "icons" / "Icon-maskable-192.png",
    )
    _save(
        _on_field(512, fraction=MASKABLE_SAFE_FRACTION, squircle=False),
        WEB / "icons" / "Icon-maskable-512.png",
    )

    # flutter_launcher_icons source, and the PNG Strava registration asks for.
    _save(_on_field(512), ROOT / "assets" / "app_icon.png")
    # Android adaptive icon, as two layers the launcher parallaxes and masks.
    # The background is shipped as an image rather than pubspec's flat colour so
    # the tile keeps its radial lift.
    _save(
        _radial_field(512).convert("RGBA"),
        ROOT / "assets" / "app_icon_background.png",
    )
    _save(
        _glyph(512 * SUPERSAMPLE, fraction=ADAPTIVE_SAFE_FRACTION).resize(
            (512, 512), Image.LANCZOS
        ),
        ROOT / "assets" / "app_icon_foreground.png",
    )

    # Android cold start, both mechanisms — see the constants above.
    for density, factor in DENSITIES.items():
        out = ANDROID_RES / f"drawable-{density}"

        size = round(LAUNCH_DP * factor)
        _save(
            _glyph(size * SUPERSAMPLE).resize((size, size), Image.LANCZOS),
            out / "launch_image.png",
        )

        size = round(SPLASH_ICON_DP * factor)
        _save(
            _glyph(
                size * SUPERSAMPLE,
                fraction=SPLASH_ICON_CONTENT_DP / SPLASH_ICON_DP,
            ).resize((size, size), Image.LANCZOS),
            out / "splash_icon.png",
        )

    print("Done. Next: cd flutter_client && dart run flutter_launcher_icons")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
