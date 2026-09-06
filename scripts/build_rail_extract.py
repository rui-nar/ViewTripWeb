#!/usr/bin/env python
"""Build a rail-only OSM extract for one region (issue #345, phase 1).

Route resolution needs three things from OpenStreetMap: railway ways, train
route relations, and stations carrying a UIC code. Overpass answers those over
the network today, and the answers are large enough that fair use bans us. The
same data, filtered out of a Geofabrik country extract, is three orders of
magnitude smaller: Denmark 494 MB -> 0.6 MB, Germany 4.83 GB -> ~20 MB.

**The raw extracts must never reach the server, the repo, or an image.** Europe
raw is 34.9 GB and the VPS has 40 GB total. So this script runs in CI, on a
throwaway runner: download, filter, publish the small result, delete the rest.
It removes the source and the intermediate as soon as each is consumed rather
than at the end, so peak disk stays near one raw extract.

Two steps, in that order for a reason:

1. ``osmium tags-filter`` (C++) does the pass over the raw file. A pyosmium
   pass with a per-object Python callback measured 2,022 s for Germany in the
   spike; the CLI does the same reduction in a couple of minutes. But
   tags-filter can only OR tag patterns together — it cannot express "railway
   ways *without* a service tag" or "station *and* uic_ref" — so it can only
   over-select.
2. A pyosmium pass applies the exact selection, and is cheap because it runs
   over step 1's output (Denmark: 1 MB) rather than the raw extract.

The selection must match what src/services/overpass_service.py asks Overpass
for today, element for element. Anything else changes route results for reasons
unrelated to moving the data source, which is the one thing this migration must
not do.

Usage:

    python scripts/build_rail_extract.py regions --json
    python scripts/build_rail_extract.py build europe/denmark --out-dir dist
    python scripts/build_rail_extract.py manifest --out-dir dist

Requires the ``osmium`` CLI (Debian/Ubuntu: ``apt-get install osmium-tool``).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

import osmium
import requests
import yaml

_REPO_ROOT = Path(__file__).resolve().parent.parent
REGIONS_CONFIG = _REPO_ROOT / "config" / "rail_regions.yml"

GEOFABRIK_BASE = "https://download.geofabrik.de"

# Bumped only when the manifest's shape changes; phase 2 reads it to decide
# whether it understands the file at all.
MANIFEST_SCHEMA = 1

MANIFEST_NAME = "manifest.json"
ENTRY_SUFFIX = "-rail.entry.json"
EXTRACT_SUFFIX = "-rail.osm.pbf"

# ---------------------------------------------------------------------------
# The selection — must mirror src/services/overpass_service.py
# ---------------------------------------------------------------------------
#
#   ways       way["railway"~"^(rail|narrow_gauge|light_rail)$"]["service"!~"."]
#              _via_coordinate_fallback's bounding-box query. The `service`
#              exclusion keeps sidings and yard tracks out of the graph; the
#              spike showed including them *breaks* routes that work today,
#              because _nearest_node snaps to the closest node regardless of
#              which connected component it lies in.
#   relations  rel["route"="train"]
#              _route_relation_segment / _via_train_relations_endpoints.
#   nodes      node["railway"~"^(station|halt)$"]["uic_ref"]
#              _find_station_near, which strategy A needs to get a UIC code.
#
# Two places where the live Overpass queries are *broader* than this, and this
# file deliberately is not — the plan and the spike's reference counts both fix
# the selection as written above, and widening it here would change route
# results while the migration is meant to change only where the data comes
# from. Phase 3 has to decide what to do about each, and phase 4's comparison
# period is where the difference would show up:
#
#   - _route_relation_segment also accepts route=railway and route=light_rail,
#     and _via_train_relations_endpoints matches
#     rel["route"~"^(train|railway|light_rail)$"].
#   - _find_station_near also queries ways and relations tagged
#     railway=station|halt with a uic_ref (stations mapped as polygons), taking
#     their centre.
#
# Adding either is a config-free code change here plus a rebuild; the fixture
# test's counts are what would tell you it happened.
RAIL_WAY_TYPES = frozenset({"rail", "narrow_gauge", "light_rail"})
STATION_RAILWAY_TYPES = frozenset({"station", "halt"})
TRAIN_ROUTE = "train"


def is_rail_way(tags: Mapping[str, str]) -> bool:
    """True for a way the coordinate-fallback graph is built from."""
    return tags.get("railway") in RAIL_WAY_TYPES and "service" not in tags


def is_train_relation(tags: Mapping[str, str]) -> bool:
    """True for a route relation strategies A and B search."""
    return tags.get("route") == TRAIN_ROUTE


def is_uic_station(tags: Mapping[str, str]) -> bool:
    """True for a station node that can answer a UIC lookup."""
    return tags.get("railway") in STATION_RAILWAY_TYPES and bool(tags.get("uic_ref"))


@dataclass(frozen=True)
class Selection:
    """What a filtered extract contains, and where it actually reaches."""

    ways: int
    relations: int
    stations: int
    # [min_lon, min_lat, max_lon, max_lat] over every node written — the true
    # extent of the rail data, not the country's nominal box. Phase 3 uses it
    # to pick a region for a coordinate, so a nominal box would claim coverage
    # the file does not have.
    bbox: list[float]


# ---------------------------------------------------------------------------
# Coverage configuration
# ---------------------------------------------------------------------------

def load_regions(path: Path = REGIONS_CONFIG) -> list[str]:
    """Return the configured Geofabrik region paths.

    Coverage is configuration (plan, phase 0): adding a country is an edit here
    plus a rebuild, never a code change.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    regions = data["regions"]
    if not regions:
        raise ValueError(f"{path} lists no regions")

    slugs = [region_slug(r) for r in regions]
    duplicates = sorted({s for s in slugs if slugs.count(s) > 1})
    if duplicates:
        # Output file names are keyed on the slug, so a collision would have one
        # region silently overwrite another in the published artifact.
        raise ValueError(f"{path}: region file names collide: {duplicates}")
    return list(regions)


def region_slug(region: str) -> str:
    """``europe/germany`` -> ``germany`` — the artifact's file-name stem."""
    return region.rstrip("/").rsplit("/", 1)[-1]


def source_url(region: str) -> str:
    return f"{GEOFABRIK_BASE}/{region}-latest.osm.pbf"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------

def download(url: str, dest: Path) -> Path:
    """Stream a Geofabrik extract to disk.

    Streamed, never held in memory: these are gigabytes.
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1 << 20):
                handle.write(chunk)
    return dest


def prefilter(source: Path, dest: Path) -> Path:
    """Reduce a raw extract to a rail superset with the osmium CLI.

    Over-selects on purpose (see the module docstring): it keeps service ways
    and station nodes without a UIC code, which ``select`` then drops. What it
    buys is the two-orders-of-magnitude reduction that makes the exact pass
    affordable in Python.

    Referenced objects are kept — the default — because a way without its nodes
    has no geometry.
    """
    if shutil.which("osmium") is None:
        raise RuntimeError(
            "the osmium CLI is required (Debian/Ubuntu: apt-get install osmium-tool)"
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "osmium", "tags-filter", "--overwrite",
            "-o", str(dest), str(source),
            f"n/railway={','.join(sorted(STATION_RAILWAY_TYPES))}",
            f"w/railway={','.join(sorted(RAIL_WAY_TYPES))}",
            f"r/route={TRAIN_ROUTE}",
        ],
        check=True,
    )
    return dest


def select(source: Path, dest: Path) -> Selection:
    """Write the exact selection, and report what it holds.

    Two passes over ``source``. The first collects the nodes the kept ways
    reference, because a way whose nodes were dropped is geometry we cannot
    reconstruct; the second writes. Splitting them is what keeps the output at
    the selection's own size instead of dragging in the nodes of every way the
    prefilter over-selected.

    Per-object OSM metadata (version, timestamp, changeset, user) is dropped:
    nothing downstream reads it and it is ~15 % of the file.
    """
    wanted_nodes: set[int] = set()
    ways = relations = stations = 0

    for way in osmium.FileProcessor(str(source), osmium.osm.WAY):
        if is_rail_way(way.tags):
            wanted_nodes.update(node.ref for node in way.nodes)

    min_lon = min_lat = 180.0
    max_lon = max_lat = -180.0
    writer = osmium.SimpleWriter(
        osmium.io.File(str(dest), "pbf,add_metadata=false"), overwrite=True
    )
    try:
        for obj in osmium.FileProcessor(str(source)):
            if obj.is_node():
                station = is_uic_station(obj.tags)
                if not station and obj.id not in wanted_nodes:
                    continue
                if station:
                    stations += 1
                writer.add_node(obj)
                lon, lat = obj.location.lon, obj.location.lat
                min_lon, max_lon = min(min_lon, lon), max(max_lon, lon)
                min_lat, max_lat = min(min_lat, lat), max(max_lat, lat)
            elif obj.is_way():
                if is_rail_way(obj.tags):
                    ways += 1
                    writer.add_way(obj)
            elif is_train_relation(obj.tags):
                relations += 1
                writer.add_relation(obj)
    finally:
        writer.close()

    if not stations and not ways:
        # An empty result means the filter matched nothing at all, which for a
        # European country means the selection or the source is wrong. Failing
        # here beats publishing a file that resolves every route to a straight
        # line.
        raise RuntimeError(f"{source} yielded no rail data")

    return Selection(
        ways=ways,
        relations=relations,
        stations=stations,
        bbox=[round(v, 5) for v in (min_lon, min_lat, max_lon, max_lat)],
    )


def source_date(pbf: Path) -> str:
    """The extract's own date, from the PBF header — the artifact's version.

    Geofabrik stamps every extract with the replication timestamp it was cut
    at. Using it rather than the build date means a rebuild of an unchanged
    extract is recognisably the same data.
    """
    reader = osmium.io.Reader(str(pbf), osmium.osm.osm_entity_bits.NOTHING)
    try:
        stamp = reader.header().get("osmosis_replication_timestamp")
    finally:
        reader.close()
    if not stamp:
        raise RuntimeError(f"{pbf} has no replication timestamp in its header")
    return stamp[:10]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def manifest_entry(
    region: str, extract: Path, selection: Selection, date: str
) -> dict:
    """One region's manifest record (the phase 1 / phase 2 contract)."""
    return {
        "region": region,
        "file": extract.name,
        "source": source_url(region),
        "source_date": date,
        "sha256": sha256_file(extract),
        "bytes": extract.stat().st_size,
        "ways": selection.ways,
        "relations": selection.relations,
        "stations": selection.stations,
        "bbox": selection.bbox,
    }


def merge_manifest(entries: Iterable[dict], generated_at: str | None = None) -> dict:
    """Combine per-region entries into the published manifest."""
    if generated_at is None:
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "regions": sorted(entries, key=lambda entry: entry["region"]),
    }


def verify_manifest(manifest: dict, directory: Path) -> None:
    """Check every entry against the file it describes.

    Runs in CI before publishing: a region whose build half-failed, or whose
    artifact was truncated in transit between jobs, must not be published as if
    it were whole.
    """
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"unknown manifest schema: {manifest.get('schema')!r}")
    for entry in manifest["regions"]:
        path = directory / entry["file"]
        if not path.is_file():
            raise ValueError(f"{entry['region']}: missing {entry['file']}")
        size = path.stat().st_size
        if size != entry["bytes"]:
            raise ValueError(
                f"{entry['region']}: {entry['file']} is {size} bytes, "
                f"manifest says {entry['bytes']}"
            )
        digest = sha256_file(path)
        if digest != entry["sha256"]:
            raise ValueError(f"{entry['region']}: {entry['file']} checksum mismatch")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def build(
    region: str,
    out_dir: Path,
    work_dir: Path,
    source: Path | None = None,
    keep_source: bool = False,
) -> dict:
    """Produce one region's filtered extract and manifest entry."""
    slug = region_slug(region)
    out_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    downloaded = source is None
    if downloaded:
        source = work_dir / f"{slug}-source.osm.pbf"
        url = source_url(region)
        print(f"[{slug}] downloading {url}", flush=True)
        download(url, source)
    print(f"[{slug}] source {source.stat().st_size / 1e6:.0f} MB "
          f"(+{time.monotonic() - started:.0f}s)", flush=True)

    date = source_date(source)
    intermediate = work_dir / f"{slug}-prefilter.osm.pbf"
    prefilter(source, intermediate)
    print(f"[{slug}] prefiltered to {intermediate.stat().st_size / 1e6:.1f} MB "
          f"(+{time.monotonic() - started:.0f}s)", flush=True)

    # Freed the moment it is no longer needed, not at the end: a runner has to
    # hold one raw extract, never two.
    if downloaded and not keep_source:
        source.unlink()

    extract = out_dir / f"{slug}{EXTRACT_SUFFIX}"
    selection = select(intermediate, extract)
    intermediate.unlink()

    entry = manifest_entry(region, extract, selection, date)
    (out_dir / f"{slug}{ENTRY_SUFFIX}").write_text(
        json.dumps(entry, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"[{slug}] {entry['bytes'] / 1e6:.2f} MB, ways={selection.ways} "
        f"relations={selection.relations} stations={selection.stations} "
        f"bbox={selection.bbox} source_date={date} "
        f"(+{time.monotonic() - started:.0f}s)",
        flush=True,
    )
    return entry


def collect_manifest(out_dir: Path) -> dict:
    """Merge the entry files in ``out_dir`` into a verified manifest."""
    entries = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in sorted(out_dir.glob(f"*{ENTRY_SUFFIX}"))
    ]
    if not entries:
        raise RuntimeError(f"no {ENTRY_SUFFIX} files in {out_dir}")
    manifest = merge_manifest(entries)
    verify_manifest(manifest, out_dir)
    (out_dir / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    p_regions = sub.add_parser("regions", help="list the configured regions")
    p_regions.add_argument("--json", action="store_true",
                           help="emit a JSON array (the workflow's build matrix)")

    p_build = sub.add_parser("build", help="filter one region")
    p_build.add_argument("region", help="Geofabrik path, e.g. europe/denmark")
    p_build.add_argument("--out-dir", type=Path, default=Path("dist/rail"))
    p_build.add_argument("--work-dir", type=Path, default=Path("dist/rail-work"))
    p_build.add_argument("--source", type=Path,
                         help="use a local .osm.pbf instead of downloading")
    p_build.add_argument("--keep-source", action="store_true",
                         help="keep the downloaded raw extract (local debugging only)")

    p_manifest = sub.add_parser("manifest", help="merge entry files into manifest.json")
    p_manifest.add_argument("--out-dir", type=Path, default=Path("dist/rail"))

    args = parser.parse_args(argv[1:])

    if args.command == "regions":
        regions = load_regions()
        print(json.dumps(regions) if args.json else "\n".join(regions))
        return 0

    if args.command == "build":
        build(args.region, args.out_dir, args.work_dir,
              source=args.source, keep_source=args.keep_source)
        return 0

    manifest = collect_manifest(args.out_dir)
    print(f"{len(manifest['regions'])} regions verified in {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
