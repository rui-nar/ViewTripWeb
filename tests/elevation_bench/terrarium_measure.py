"""Measure the terrarium tileset against a 1 m lidar terrain model (#386, unit 2).

    python -m tests.elevation_bench.terrarium_measure [--cache DIR] [--zooms 12 13 14 15]

Not a test and not collected by pytest: it downloads ~20 MB per reference tile
and a few hundred terrarium tiles. It exists so that the go/no-go gate on
terrain substitution is a number anyone can re-derive, not a figure quoted from
a transcript. Four review rounds on unit 1 found a figure that could not be
reproduced every time one was written down.

What it answers
---------------
The flatness oracle asks one question per 500 m window of path: does the terrain
model show relief here? Unit 1 established, on synthetic surfaces, that the
answer is reliable only while the model's own within-window error stays around
0.5 m. That cannot be read off a spec sheet. So this asks the question directly,
on real tiles, against ground truth:

* **Truth** is Berlin's DGM1 — airborne lidar, bare earth, 1 m grid, licensed
  dl-de/zero-2-0 from https://gdi.berlin.de/data/dgm1/atom/.
* For every 500 m window along a set of transects, the verdict the oracle would
  reach on terrarium is compared with the verdict it would reach on the lidar.
  That confusion matrix IS the gate, measured rather than inferred.
* The error series (terrarium minus lidar) is also characterised — its
  within-window deviation and its correlation length — so the result can be
  located on unit 1's synthetic table and understood, not just reported.

Why Berlin
----------
Not only because it is flat. The lidar is BARE EARTH, while terrarium over
Germany comes from SRTM, a radar SURFACE model that sees rooftops and tree
canopy. So Berlin separates three things a flat test could otherwise conflate:
open flat ground (Tempelhofer Feld, a former airfield), flat ground under a
dense city, and flat ground under forest — plus genuine relief for the other
side of the verdict. If SRTM reads a city block as relief, the oracle would
leave the phantom climb in place in exactly the places people travel.

A constant vertical datum offset (DHHN2016 against EGM96) does not matter to a
range or to a gain, and every error statistic here is taken about a mean.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
import zipfile
from typing import Dict, List, Tuple

try:
    import numpy as np
except ImportError:                                    # pragma: no cover
    raise SystemExit(
        "terrarium_measure needs numpy, which is not an application dependency: "
        "pip install numpy") from None
import requests

from src.models.track_edit import (
    TERRAIN_RELIEF_M,
    TERRAIN_WINDOW_M,
    _relief,
    _relief_span,
    _terrain_windows,
)
from tests.elevation_bench.tile_reader import TerrariumReader
from tests.elevation_bench.utm import from_utm, to_utm

DGM1_URL = "https://gdi.berlin.de/data/dgm1/atom/DGM1_{e}_{n}.zip"
TILE_KM = 2
SAMPLE_M = 5.0

# ── The reference ────────────────────────────────────────────────────────────
class Dgm1Tile:
    """One 2 km x 2 km Berlin DGM1 tile, as a 2000 x 2000 grid of heights."""

    def __init__(self, e_km: int, n_km: int, cache: str):
        self.e0, self.n0 = e_km * 1000, n_km * 1000
        path = os.path.join(cache, f"DGM1_{e_km}_{n_km}.npy")
        if os.path.exists(path):
            self.grid = np.load(path)
            return
        zpath = os.path.join(cache, f"DGM1_{e_km}_{n_km}.zip")
        if not os.path.exists(zpath):
            resp = requests.get(DGM1_URL.format(e=e_km, n=n_km), timeout=600)
            resp.raise_for_status()
            with open(zpath, "wb") as handle:
                handle.write(resp.content)
        with zipfile.ZipFile(zpath) as archive:
            member = next(m for m in archive.namelist() if m.endswith(".xyz"))
            raw = np.loadtxt(io.TextIOWrapper(archive.open(member)),
                             dtype=np.float64)
        # Place every row by its own coordinates rather than trusting the file's
        # row order — an ordering assumption that is wrong by one row is a 1 m
        # shift that would read as terrarium error.
        cols = np.round(raw[:, 0] - self.e0 - 0.5).astype(int)
        rows = np.round(raw[:, 1] - self.n0 - 0.5).astype(int)
        size = TILE_KM * 1000
        ok = (cols >= 0) & (cols < size) & (rows >= 0) & (rows < size)
        grid = np.full((size, size), np.nan, dtype=np.float32)
        grid[rows[ok], cols[ok]] = raw[ok, 2]
        self.grid = grid
        np.save(path, grid)

    def height(self, easting: float, northing: float) -> float:
        """Bilinear over pixel centres, which sit at x.5 in the file."""
        cx = easting - self.e0 - 0.5
        cy = northing - self.n0 - 0.5
        x0, y0 = int(math.floor(cx)), int(math.floor(cy))
        fx, fy = cx - x0, cy - y0
        g = self.grid
        if not (0 <= x0 < g.shape[1] - 1 and 0 <= y0 < g.shape[0] - 1):
            return float("nan")
        return float(g[y0, x0] * (1 - fx) * (1 - fy) + g[y0, x0 + 1] * fx * (1 - fy)
                     + g[y0 + 1, x0] * (1 - fx) * fy + g[y0 + 1, x0 + 1] * fx * fy)


# ── A second candidate: Copernicus GLO-30 ────────────────────────────────────
COPERNICUS_URL = ("https://copernicus-dem-30m.s3.amazonaws.com/"
                  "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM/"
                  "Copernicus_DSM_COG_10_N{lat:02d}_00_E{lon:03d}_00_DEM.tif")


class CopernicusTile:
    """One 1 x 1 degree Copernicus GLO-30 tile, read without GDAL.

    Measurement only. It is here because the plan named Copernicus as the second
    attempt if terrarium failed the gate, and whether it passes decides whether
    the ~150 MB GDAL dependency it would need in production is worth
    discussing at all.

    **PixelIsPoint.** The tile's GeoKey 1025 is 2, so its tiepoint is the CENTRE
    of pixel (0, 0), not its corner — the opposite convention to a Web Mercator
    tile. Pixel (row, col) therefore sits at exactly
    ``lon0 + col * dlon, lat0 - row * dlat`` with no half-pixel shift. Reading it
    with terrarium's rule would move every sample ~15 m, an error that would be
    charged to the tileset.

    Longitude spacing depends on latitude band: between 50 and 60 degrees it is
    1.5 arc-seconds, not 1, so the grid is 2400 x 3600 rather than square. Both
    spacings are read from the file rather than assumed.
    """

    def __init__(self, lat_deg: int, lon_deg: int, cache: str):
        from PIL import Image
        Image.MAX_IMAGE_PIXELS = None
        path = os.path.join(cache, f"copernicus_N{lat_deg}_E{lon_deg}.tif")
        if not os.path.exists(path):
            resp = requests.get(COPERNICUS_URL.format(lat=lat_deg, lon=lon_deg),
                                timeout=600)
            resp.raise_for_status()
            with open(path, "wb") as handle:
                handle.write(resp.content)
        image = Image.open(path)
        tags = image.tag_v2
        keys = tags.get(34735)
        geokeys = {keys[4 + i * 4]: keys[4 + i * 4 + 3]
                   for i in range(keys[3])}
        if geokeys.get(1025) != 2:
            raise ValueError("expected PixelIsPoint; the pixel-centre maths "
                             "below would be half a pixel wrong")
        self.dlon, self.dlat = tags[33550][0], tags[33550][1]
        self.lon0, self.lat0 = tags[33922][3], tags[33922][4]
        self.grid = np.array(image, dtype=np.float32)

    def elevation(self, lat: float, lon: float):
        col = (lon - self.lon0) / self.dlon
        row = (self.lat0 - lat) / self.dlat
        c0, r0 = int(math.floor(col)), int(math.floor(row))
        fc, fr = col - c0, row - r0
        g = self.grid
        if not (0 <= c0 < g.shape[1] - 1 and 0 <= r0 < g.shape[0] - 1):
            return None
        return float(g[r0, c0] * (1 - fc) * (1 - fr) + g[r0, c0 + 1] * fc * (1 - fr)
                     + g[r0 + 1, c0] * (1 - fc) * fr + g[r0 + 1, c0 + 1] * fc * fr)


# ── Sites ────────────────────────────────────────────────────────────────────
#: (label, kind, latitude, longitude). The tile is whichever 2 km DGM1 tile the
#: point falls in; transects run across that tile. ``kind`` is a HYPOTHESIS
#: about the ground, and the lidar — not this label — decides each window.
SITES = [
    ("Tempelhofer Feld", "open flat", 52.4735, 13.4015),
    ("Mitte", "flat under a dense city", 52.5170, 13.3888),
    ("Grunewald", "flat under forest", 52.4700, 13.2250),
    ("Teufelsberg", "relief (rubble hill)", 52.4975, 13.2412),
    ("Mueggelberge", "relief (natural hills, forest)", 52.4167, 13.6333),
]


def tile_of(lat: float, lon: float) -> Tuple[int, int]:
    e, n = to_utm(lat, lon)
    return (int(e // 2000) * 2, int(n // 2000) * 2)


def transects(e0: float, n0: float) -> List[List[Tuple[float, float]]]:
    """East-west and north-south lines across one tile, inset from its edges."""
    lines = []
    inset, length = 50.0, TILE_KM * 1000 - 100.0
    count = int(length / SAMPLE_M) + 1
    for offset in (250.0, 750.0, 1250.0, 1750.0):
        lines.append([(e0 + inset + i * SAMPLE_M, n0 + offset)
                      for i in range(count)])
        lines.append([(e0 + offset, n0 + inset + i * SAMPLE_M)
                      for i in range(count)])
    return lines


# ── Measurement ──────────────────────────────────────────────────────────────
def correlation_length_m(error: np.ndarray) -> float:
    """Distance at which the error's autocorrelation first drops below 1/e."""
    e = error - error.mean()
    denom = float((e * e).sum())
    if denom <= 0:
        return float("nan")
    for lag in range(1, len(e) // 2):
        if float((e[:-lag] * e[lag:]).sum()) / denom < 1 / math.e:
            return lag * SAMPLE_M
    return float("inf")


def measure_site(label, kind, lat, lon, elevation, cache) -> Dict:
    """``elevation`` is any ``(lat, lon) -> Optional[float]`` source."""
    e_km, n_km = tile_of(lat, lon)
    tile = Dgm1Tile(e_km, n_km, cache)
    counts = {"flat->flat": 0, "flat->relief": 0,
              "relief->relief": 0, "relief->flat": 0, "skipped": 0}
    whole_sd, window_sd, corr = [], [], []

    for line in transects(tile.e0, tile.n0):
        ref = np.array([tile.height(e, n) for e, n in line])
        ter_raw = [elevation(*from_utm(e, n)) for e, n in line]
        if np.isnan(ref).any() or any(v is None for v in ter_raw):
            counts["skipped"] += 1
            continue
        ter = np.array(ter_raw, dtype=float)
        dist_km = [i * SAMPLE_M / 1000.0 for i in range(len(line))]

        err = ter - ref
        whole_sd.append(float(err.std()))
        corr.append(correlation_length_m(err))

        n = len(line)
        for lo, hi in _terrain_windows(dist_km, n, TERRAIN_WINDOW_M):
            span = _relief_span(lo, hi, n, TERRAIN_WINDOW_M, dist_km)
            r_win, t_win = list(ref[span]), list(ter[span])
            if len(r_win) < 3:
                continue
            window_sd.append(float(np.std(err[span])))
            truth = "relief" if _relief(r_win) >= TERRAIN_RELIEF_M else "flat"
            got = "relief" if _relief(t_win) >= TERRAIN_RELIEF_M else "flat"
            counts[f"{truth}->{got}"] += 1

    return {
        "label": label, "kind": kind, "tile": f"{e_km}_{n_km}",
        "counts": counts,
        "error_sd_whole": float(np.median(whole_sd)) if whole_sd else float("nan"),
        "error_sd_window": float(np.median(window_sd)) if window_sd else float("nan"),
        "corr_length_m": float(np.median(corr)) if corr else float("nan"),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cache", default=os.path.join(
        os.path.expanduser("~"), ".cache", "viewtrip-terrarium-measure"))
    parser.add_argument("--source", choices=("terrarium", "copernicus"),
                        default="terrarium")
    parser.add_argument("--zooms", type=int, nargs="+", default=[13],
                        help="terrarium only")
    args = parser.parse_args(argv)
    os.makedirs(args.cache, exist_ok=True)

    if args.source == "copernicus":
        sources = [("copernicus GLO-30", CopernicusTile(52, 13, args.cache).elevation)]
    else:
        sources = [(f"terrarium zoom {z}",
                    TerrariumReader(os.path.join(args.cache, "tiles"),
                                    zoom=z).elevation)
                   for z in args.zooms]

    for title, elevation in sources:
        print(f"\n=== {title}  (window {TERRAIN_WINDOW_M:.0f} m, relief "
              f"threshold {TERRAIN_RELIEF_M:.0f} m)")
        print(f"{'site':18s} {'tile':10s} {'err sd':>7s} {'in-win sd':>9s} "
              f"{'corr len':>9s}   verdicts: truth->model")
        for label, kind, lat, lon in SITES:
            result = measure_site(label, kind, lat, lon, elevation, args.cache)
            c = result["counts"]
            print(f"{label:18s} {result['tile']:10s} "
                  f"{result['error_sd_whole']:7.2f} "
                  f"{result['error_sd_window']:9.2f} "
                  f"{result['corr_length_m']:8.0f}m   "
                  f"flat->flat {c['flat->flat']:3d}  flat->RELIEF {c['flat->relief']:3d}  "
                  f"relief->relief {c['relief->relief']:3d}  relief->FLAT {c['relief->flat']:3d}"
                  + (f"  skipped {c['skipped']}" if c["skipped"] else ""))
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
