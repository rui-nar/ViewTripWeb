"""Measure global terrain models against 1 m lidar, for the #386 oracle.

    python -m tests.elevation_bench.terrarium_measure [--models terrarium copernicus gedtm]

Not a test, and not collected by pytest: it downloads ~20 MB per lidar tile,
a Copernicus tile and a few hundred terrarium tiles, and needs numpy (and
rasterio for GEDTM30), neither of which the application depends on. It exists so
the verdict on terrain substitution is a number anyone can re-derive rather than
a figure quoted from a transcript.

What it measures, and what it deliberately does not
--------------------------------------------------
The flatness oracle (:func:`src.models.track_edit.terrain_corrected_gain`) asks
one question per 500 m of path: does the terrain model show relief here? Its two
wrong answers are NOT symmetric, and the first version of this measurement
treated them as if they were:

* **Flat ground read as relief** keeps the recording. That is today's behaviour:
  the phantom climb is not removed, and nothing is made worse. A **missed fix**.
* **Relief read as flat** swaps the model in over a real hill. That can erase
  climb that happened. **Harm.**

Counting both as "misreads" made a safe partial fix look like a failed design:
the headline "26 of 26 flat windows misread" in a city was entirely the harmless
kind. So the primary output here is the **outcome** — what the shipped oracle
reports end to end against the truth, whether it ever does worse than the
recording alone, and whether it ever erases real climb — with the per-window
verdicts kept as a diagnostic and their two kinds named for what they are.

Ground truth
------------
Berlin's DGM1: airborne lidar, BARE EARTH, 1 m grid, licensed dl-de/zero-2-0,
https://gdi.berlin.de/data/dgm1/atom/. The sites separate causes that a flat
test would conflate:

* **Tempelhofer Feld** — a former airfield. Transects are confined to a
  rectangle kept at least 60 m inside the park on every side. An earlier version
  used a whole 2 km lidar tile and called it "open, no buildings, no trees"; most
  of that tile is streets, houses and the Ringbahn, and most of the misreads it
  reported came from them.
* **Mitte** — flat ground under a dense city.
* **Grunewald** — flat-ish ground under forest.
* **Teufelsberg**, **Mueggelberge** — real relief.

"Truth" for a gain is the gain pipeline applied to the lidar itself, so every
figure is compared like for like and the pipeline's own smoothing floor cancels.

The recording
-------------
The oracle never sees a perfect path. Each transect is recorded the way unit 1
models a phone: AR(1) vertical drift, AR(1) horizontal drift, and the path
smoothed over 100 m of ground before the model is read. Two drift settings, four
seeds each.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
import zipfile
from typing import Callable, Dict, Sequence, Tuple

try:
    import numpy as np
except ImportError:                                    # pragma: no cover
    raise SystemExit(
        "terrarium_measure needs numpy, which is not an application "
        "dependency: pip install numpy") from None
import requests

from src.models.track_edit import (
    TERRAIN_RELIEF_M,
    TERRAIN_WINDOW_M,
    _relief,
    _relief_span,
    _terrain_windows,
    elevation_gain,
    terrain_corrected_gain,
)
from tests.elevation_bench import utm
from tests.elevation_bench.generators import _ar1
from tests.elevation_bench.tile_reader import TILE_SIZE, TerrariumReader

CACHE = os.path.join(os.path.expanduser("~"), ".cache",
                     "viewtrip-terrarium-measure")
DGM1_URL = "https://gdi.berlin.de/data/dgm1/atom/DGM1_{e}_{n}.zip"
SAMPLE_M = 5.0
SPEED_MS = 5.0
PATH_SMOOTH_M = 100.0
HORIZONTAL_SIGMA_M = 5.0
#: (vertical sigma m, correlation time s) — phone-class altitude drift.
RECORDING_NOISE = ((4.0, 60.0), (2.5, 20.0))
SEEDS = (0, 1, 2, 3)


# ── Coordinates, vectorised ──────────────────────────────────────────────────
def from_utm_array(easting, northing):
    """:func:`utm.from_utm` over arrays — the same constants, so the tests that
    pin the scalar version pin this one's arithmetic too."""
    xi = northing / (utm._K0 * utm._AA)
    eta = (easting - utm._FE) / (utm._K0 * utm._AA)
    xi_p, eta_p = xi.copy(), eta.copy()
    for j, b in enumerate(utm._BETA, start=1):
        xi_p = xi_p - b * np.sin(2 * j * xi) * np.cosh(2 * j * eta)
        eta_p = eta_p - b * np.cos(2 * j * xi) * np.sinh(2 * j * eta)
    chi = np.arcsin(np.sin(xi_p) / np.cosh(eta_p))
    phi = chi.copy()
    for j, d in enumerate(utm._DELTA, start=1):
        phi = phi + d * np.sin(2 * j * chi)
    lam = utm._LON0 + np.arctan2(np.sinh(eta_p), np.cos(xi_p))
    return np.degrees(phi), np.degrees(lam)


def bilinear(grid, col, row):
    """Bilinear read at fractional (col, row) pixel-CENTRE positions; NaN outside
    the grid rather than a clamped edge value."""
    c0 = np.floor(col).astype(int)
    r0 = np.floor(row).astype(int)
    fc, fr = col - c0, row - r0
    ok = (c0 >= 0) & (c0 < grid.shape[1] - 1) & (r0 >= 0) & (r0 < grid.shape[0] - 1)
    c0 = np.clip(c0, 0, grid.shape[1] - 2)
    r0 = np.clip(r0, 0, grid.shape[0] - 2)
    value = (grid[r0, c0] * (1 - fc) * (1 - fr) + grid[r0, c0 + 1] * fc * (1 - fr)
             + grid[r0 + 1, c0] * (1 - fc) * fr + grid[r0 + 1, c0 + 1] * fc * fr)
    return np.where(ok, value, np.nan)


# ── Ground truth ─────────────────────────────────────────────────────────────
def dgm1_grid(e_km: int, n_km: int):
    """One 2 km Berlin DGM1 tile as a 2000 x 2000 grid, row 0 at the SOUTH edge."""
    path = os.path.join(CACHE, f"DGM1_{e_km}_{n_km}.npy")
    if os.path.exists(path):
        return np.load(path).astype(np.float64)
    zpath = os.path.join(CACHE, f"DGM1_{e_km}_{n_km}.zip")
    if not os.path.exists(zpath):
        resp = requests.get(DGM1_URL.format(e=e_km, n=n_km), timeout=600)
        resp.raise_for_status()
        with open(zpath, "wb") as handle:
            handle.write(resp.content)
    with zipfile.ZipFile(zpath) as archive:
        member = next(m for m in archive.namelist() if m.endswith(".xyz"))
        raw = np.loadtxt(io.TextIOWrapper(archive.open(member)), dtype=np.float64)
    # Place every point by its own coordinates rather than by file order: a row
    # off by one is a 1 m shift, and it would be charged to the model.
    e0, n0 = e_km * 1000, n_km * 1000
    cols = np.round(raw[:, 0] - e0 - 0.5).astype(int)
    rows = np.round(raw[:, 1] - n0 - 0.5).astype(int)
    ok = (cols >= 0) & (cols < 2000) & (rows >= 0) & (rows < 2000)
    grid = np.full((2000, 2000), np.nan, dtype=np.float32)
    grid[rows[ok], cols[ok]] = raw[ok, 2]
    np.save(path, grid)
    return grid.astype(np.float64)


class Lidar:
    """One or more DGM1 tiles side by side, sampled in UTM 33N."""

    def __init__(self, tiles: Sequence[Tuple[int, int]]):
        es = sorted({e for e, _ in tiles})
        ns = sorted({n for _, n in tiles})
        self.e0, self.n0 = es[0] * 1000, ns[0] * 1000
        grid = np.full((1000 * (ns[-1] - ns[0] + 2), 1000 * (es[-1] - es[0] + 2)),
                       np.nan)
        for e_km, n_km in tiles:
            r = (n_km - ns[0]) * 1000
            c = (e_km - es[0]) * 1000
            grid[r:r + 2000, c:c + 2000] = dgm1_grid(e_km, n_km)
        self.grid = grid

    def at(self, easting, northing):
        # DGM1 pixel centres sit at .5 m.
        return bilinear(self.grid, easting - self.e0 - 0.5,
                        northing - self.n0 - 0.5)


# ── The models under test ────────────────────────────────────────────────────
class Terrarium:
    name = "terrarium z13"

    def __init__(self, zoom: int = 13):
        self.zoom = zoom
        self.reader = TerrariumReader(os.path.join(CACHE, "tiles"), zoom=zoom)
        self._grids: Dict[Tuple[int, int], object] = {}

    def _grid(self, tx: int, ty: int):
        key = (tx, ty)
        if key not in self._grids:
            tile = self.reader.tile_grid(self.zoom, tx, ty)
            self._grids[key] = (np.full((TILE_SIZE, TILE_SIZE), np.nan)
                                if tile is None else
                                np.asarray(tile, dtype=np.float64).reshape(
                                    TILE_SIZE, TILE_SIZE))
        return self._grids[key]

    def _pixels(self, gx, gy):
        tx, px = np.divmod(gx, TILE_SIZE)
        ty, py = np.divmod(gy, TILE_SIZE)
        out = np.empty(gx.shape)
        for a, b in set(zip(tx.ravel().tolist(), ty.ravel().tolist())):
            mask = (tx == a) & (ty == b)
            out[mask] = self._grid(a, b)[py[mask], px[mask]]
        return out

    def at(self, lat, lon):
        world = TILE_SIZE * (1 << self.zoom)
        x = (lon + 180.0) / 360.0 * world
        s = np.sin(np.radians(lat))
        y = (0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)) * world
        # A Web Mercator pixel's value sits at its centre.
        cx, cy = x - 0.5, y - 0.5
        x0, y0 = np.floor(cx).astype(int), np.floor(cy).astype(int)
        fx, fy = cx - x0, cy - y0
        return (self._pixels(x0, y0) * (1 - fx) * (1 - fy)
                + self._pixels(x0 + 1, y0) * fx * (1 - fy)
                + self._pixels(x0, y0 + 1) * (1 - fx) * fy
                + self._pixels(x0 + 1, y0 + 1) * fx * fy)


class Copernicus:
    """Copernicus GLO-30, a SURFACE model, read with Pillow and no GDAL.

    GeoKey 1025 is 2 — PixelIsPoint — so the tiepoint is the CENTRE of pixel
    (0, 0): the opposite convention to a Web Mercator tile, asserted from the
    file rather than assumed.
    """
    name = "copernicus GLO-30 (surface)"
    URL = ("https://copernicus-dem-30m.s3.amazonaws.com/"
           "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM/"
           "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")

    def __init__(self, lat_deg: int = 52, lon_deg: int = 13):
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        path = os.path.join(CACHE, f"copernicus_N{lat_deg}_E{lon_deg}.tif")
        if not os.path.exists(path):
            resp = requests.get(self.URL.format(lat=lat_deg, lon=lon_deg),
                                timeout=600)
            resp.raise_for_status()
            with open(path, "wb") as handle:
                handle.write(resp.content)
        image = Image.open(path)
        tags = image.tag_v2
        keys = tags[34735]
        geokeys = {keys[4 + i * 4]: keys[4 + i * 4 + 3] for i in range(keys[3])}
        if geokeys.get(1025) != 2:
            raise ValueError("expected PixelIsPoint")
        self.dlon, self.dlat = tags[33550][0], tags[33550][1]
        self.lon0, self.lat0 = tags[33922][3], tags[33922][4]
        self.grid = np.array(image, dtype=np.float64)

    def at(self, lat, lon):
        return bilinear(self.grid, (lon - self.lon0) / self.dlon,
                        (self.lat0 - lat) / self.dlat)


class Gedtm30:
    """GEDTM30 v1.2 — a global BARE-EARTH model, CC-BY-4.0 (OpenLandMap).

    Needs rasterio to range-read one window of a global Cloud Optimized GeoTIFF;
    rasterio is not an application dependency. PixelIsArea: the transform's
    origin is a pixel CORNER. Scale, offset and nodata are applied from the
    file's own metadata rather than assumed.
    """
    name = "GEDTM30 v1.2 (bare earth)"
    URL = ("/vsicurl/https://s3.opengeohub.org/global/dtm/v1.2/"
           "gedtm_rf_m_30m_s_20060101_20151231_go_epsg.4326.3855_v1.2.tif")
    BOUNDS = (13.15, 52.38, 13.70, 52.55)          # west, south, east, north

    def __init__(self):
        path = os.path.join(CACHE, "gedtm30_berlin.npz")
        if not os.path.exists(path):
            try:
                import rasterio
                from rasterio.windows import from_bounds
            except ImportError:
                raise SystemExit("the GEDTM30 source needs rasterio: "
                                 "pip install rasterio") from None
            with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
                with rasterio.open(self.URL) as ds:
                    window = from_bounds(*self.BOUNDS, ds.transform)
                    window = window.round_offsets().round_lengths()
                    raw = ds.read(1, window=window).astype(np.float64)
                    if ds.nodata is not None:
                        raw[raw == ds.nodata] = np.nan
                    scale = (ds.scales or (1.0,))[0] or 1.0
                    offset = (ds.offsets or (0.0,))[0] or 0.0
                    t = ds.window_transform(window)
            np.savez(path, grid=raw * scale + offset,
                     transform=np.array([t.a, t.c, t.e, t.f]))
        data = np.load(path)
        self.grid = data["grid"]
        self.dlon, self.lon0, self.dlat, self.lat0 = data["transform"]

    def at(self, lat, lon):
        # PixelIsArea: half a pixel to reach centre coordinates.
        return bilinear(self.grid, (lon - self.lon0) / self.dlon - 0.5,
                        (lat - self.lat0) / self.dlat - 0.5)


MODELS: Dict[str, Callable[[], object]] = {
    "terrarium": Terrarium,
    "copernicus": Copernicus,
    "gedtm": Gedtm30,
}


# ── Sites ────────────────────────────────────────────────────────────────────
def _grid_lines(e_min, e_max, n_min, n_max, step=100.0):
    """East-west and north-south lines across a rectangle, sampled every 5 m."""
    lines = []
    for n in np.arange(n_min + step / 2, n_max, step):
        e = np.arange(e_min, e_max + 1e-9, SAMPLE_M)
        lines.append((e, np.full(e.shape, n)))
    for e in np.arange(e_min + step / 2, e_max, step):
        n = np.arange(n_min, n_max + 1e-9, SAMPLE_M)
        lines.append((np.full(n.shape, e), n))
    return lines


def _tile_lines(e_km: int, n_km: int):
    e0, n0 = e_km * 1000, n_km * 1000
    return _grid_lines(e0 + 50, e0 + 1950, n0 + 50, n0 + 1950)


#: (label, what the ground is, lidar tiles, transects)
SITES = [
    # The park interior: a rectangle at least 60 m inside Tempelhofer Feld on
    # every side, chosen once against the park's outline, so that no street,
    # house or railway reaches a transect. It straddles two lidar tiles.
    ("Tempelhofer Feld", "open flat, park interior",
     [(390, 5814), (392, 5814)],
     _grid_lines(391004.0, 392354.0, 5814350.0, 5815375.0)),
    ("Mitte", "flat, dense city", [(390, 5818)], _tile_lines(390, 5818)),
    ("Grunewald", "flat-ish, forest", [(378, 5814)], _tile_lines(378, 5814)),
    ("Teufelsberg", "relief, rubble hill", [(380, 5816)], _tile_lines(380, 5816)),
    ("Mueggelberge", "relief, natural hills", [(406, 5808)],
     _tile_lines(406, 5808)),
]


# ── Measurements ─────────────────────────────────────────────────────────────
def _smooth(values, span_m: float):
    k = max(1, int(round(span_m / SAMPLE_M)))
    if k % 2 == 0:
        k += 1
    padded = np.pad(values, k // 2, mode="edge")
    csum = np.cumsum(np.insert(padded, 0, 0.0))
    return (csum[k:] - csum[:-k]) / k


def verdicts(truth, model, window_m: float, threshold_m: float) -> Dict[str, int]:
    """Per-window verdicts, named for their consequence."""
    counts = {"flat ok": 0, "MISSED FIX": 0, "relief ok": 0, "HARM": 0}
    n = len(truth)
    dist = [i * SAMPLE_M / 1000.0 for i in range(n)]
    for lo, hi in _terrain_windows(dist, n, window_m):
        span = _relief_span(lo, hi, n, window_m, dist)
        t, m = truth[span], model[span]
        if len(t) < 3 or np.isnan(t).any() or np.isnan(m).any():
            continue
        truly_relief = _relief(list(t)) >= threshold_m
        read_relief = _relief(list(m)) >= threshold_m
        if truly_relief:
            counts["relief ok" if read_relief else "HARM"] += 1
        else:
            counts["MISSED FIX" if read_relief else "flat ok"] += 1
    return counts


def outcome(lidar: Lidar, lines, model, sigma_v: float, tau_s: float) -> Dict:
    """The shipped oracle end to end, against what the lidar says was climbed."""
    tau_samples = tau_s * SPEED_MS / SAMPLE_M
    totals = {"truth": 0.0, "recording": 0.0, "oracle": 0.0, "perfect": 0.0}
    worse = erased = runs = 0
    for index, (e, n) in enumerate(lines):
        truth = lidar.at(e, n)
        if np.isnan(truth).any():
            continue
        count = len(e)
        dist = [i * SAMPLE_M / 1000.0 for i in range(count)]
        truth_gain = elevation_gain(list(truth), dist)
        for seed in SEEDS:
            base = 1000 * index + seed
            recording = truth + np.array(_ar1(count, sigma_v, tau_samples, base))
            pe = _smooth(e + np.array(_ar1(count, HORIZONTAL_SIGMA_M,
                                           tau_samples, base + 1)), PATH_SMOOTH_M)
            pn = _smooth(n + np.array(_ar1(count, HORIZONTAL_SIGMA_M,
                                           tau_samples, base + 2)), PATH_SMOOTH_M)
            lat, lon = from_utm_array(pe, pn)
            modelled = model.at(lat, lon)
            perfect = lidar.at(pe, pn)
            if np.isnan(modelled).any() or np.isnan(perfect).any():
                continue
            recorded_gain = elevation_gain(list(recording), dist)
            oracle_gain = terrain_corrected_gain(list(recording), list(modelled),
                                                 dist)
            totals["truth"] += truth_gain
            totals["recording"] += recorded_gain
            totals["oracle"] += oracle_gain
            totals["perfect"] += terrain_corrected_gain(
                list(recording), list(perfect), dist)
            worse += abs(oracle_gain - truth_gain) > abs(
                recorded_gain - truth_gain) + 1.0
            erased += oracle_gain < truth_gain - 10.0
            runs += 1
    totals.update(worse=worse, erased=erased, runs=runs)
    return totals


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", nargs="+", choices=sorted(MODELS),
                        default=["terrarium", "copernicus"])
    args = parser.parse_args(argv)
    os.makedirs(CACHE, exist_ok=True)

    sites = [(label, kind, Lidar(tiles), lines)
             for label, kind, tiles, lines in SITES]

    for key in args.models:
        model = MODELS[key]()
        print(f"\n=== {model.name}  (window {TERRAIN_WINDOW_M:.0f} m, "
              f"relief threshold {TERRAIN_RELIEF_M:.0f} m)")
        print("  OUTCOME — the shipped oracle end to end. 'removed' is the share "
              "of the recording's excess over the truth taken away. 'worse' "
              "counts runs further from the truth than the recording alone; "
              "'erased' counts runs more than 10 m BELOW the truth.")
        for sigma_v, tau_s in RECORDING_NOISE:
            print(f"  recording drift sigma {sigma_v} m over {tau_s:.0f} s")
            print(f"  {'site':18s} {'truth':>7s} {'recorded':>9s} {'oracle':>7s} "
                  f"{'perfect':>8s} {'removed':>8s} {'worse':>9s} {'erased':>9s}")
            for label, kind, lidar, lines in sites:
                o = outcome(lidar, lines, model, sigma_v, tau_s)
                excess = o["recording"] - o["truth"]
                removed = ((o["recording"] - o["oracle"]) / excess * 100
                           if excess > 0 else float("nan"))
                print(f"  {label:18s} {o['truth']:7.0f} {o['recording']:9.0f} "
                      f"{o['oracle']:7.0f} {o['perfect']:8.0f} {removed:7.0f}% "
                      f"{o['worse']:4d}/{o['runs']:<4d}{o['erased']:4d}/{o['runs']}")
                sys.stdout.flush()

        print("  VERDICTS per window (diagnostic). MISSED FIX leaves the recording "
              "alone — no worse than today. HARM swaps the model in over a hill.")
        for label, kind, lidar, lines in sites:
            total: Dict[str, int] = {}
            errors = []
            for e, n in lines:
                truth = lidar.at(e, n)
                lat, lon = from_utm_array(e, n)
                modelled = model.at(lat, lon)
                if np.isnan(truth).any() or np.isnan(modelled).any():
                    continue
                for k, v in verdicts(truth, modelled, TERRAIN_WINDOW_M,
                                     TERRAIN_RELIEF_M).items():
                    total[k] = total.get(k, 0) + v
                errors.append(float(np.std(modelled - truth)))
            sd = float(np.median(errors)) if errors else float("nan")
            print(f"  {label:18s} {kind:26s} error sd {sd:5.2f} m  "
                  + "  ".join(f"{k} {v}" for k, v in total.items()))
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
