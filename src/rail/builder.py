"""Build a per-region rail store from a filtered rail-only ``.osm.pbf``.

The input is Phase 1's artifact — the extract already reduced to
``railway in (rail, narrow_gauge, light_rail)`` without ``service``, route
relations, and station/halt nodes with ``uic_ref``. This module makes no tag
decisions of its own beyond recognising those, so changing coverage stays a
Phase 1 concern.

Run it from Phase 1's pipeline (see docs/LOCAL_RAIL_DATA_PLAN.md — building in
CI, not on the box, is Phase 2's decision and this is the step that implements
it)::

    python -m src.rail.builder germany-rail.osm.pbf europe-germany.rail.sqlite \\
        --region europe/germany --source-date 2026-09-05

``osmium`` (pyosmium) is imported lazily: only the builder needs it, and the
builder does not run on the server.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone

from src.rail.store import SCHEMA_VERSION, clean_uic, encode_geometry

# The strategy-C selection, repeated here only to tell a rail way from a way
# that is in the file solely because a route relation references it. Those
# member ways must keep their geometry (a relation's ``out geom`` includes
# them) but must not appear in bbox or snapping results.
_RAIL_VALUES = {"rail", "narrow_gauge", "light_rail"}
_ROUTE_VALUES = {"train", "railway", "light_rail"}
_STATION_VALUES = {"station", "halt"}

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- One row per way, geometry packed as int32 lat/lon pairs (see store.py).
-- rail=0 marks a way present only as a relation member: it has geometry a
-- relation needs, but it is not track the resolver may snap to or route over.
CREATE TABLE way (
    id   INTEGER PRIMARY KEY,
    rail INTEGER NOT NULL,
    geom BLOB NOT NULL
);

-- Indexes rail ways only, so every spatial query is over track by construction.
CREATE VIRTUAL TABLE way_bbox USING rtree(id, min_lon, max_lon, min_lat, max_lat);

CREATE TABLE station (
    id  INTEGER PRIMARY KEY,      -- OSM node id
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    uic TEXT NOT NULL             -- as tagged; match on the normalised form
);
CREATE VIRTUAL TABLE station_pos USING rtree(id, min_lon, max_lon, min_lat, max_lat);

CREATE TABLE relation (
    id    INTEGER PRIMARY KEY,
    route TEXT NOT NULL,
    name  TEXT
);
CREATE TABLE relation_way (
    rel_id INTEGER NOT NULL,
    way_id INTEGER NOT NULL,
    seq    INTEGER NOT NULL
);
CREATE INDEX relation_way_rel ON relation_way(rel_id);
CREATE INDEX relation_way_way ON relation_way(way_id);

-- Strategy A asks "which relation serves both these UIC codes"; this is the
-- relation's member stations, normalised, so that question is one join.
CREATE TABLE relation_uic (
    rel_id INTEGER NOT NULL,
    uic    TEXT NOT NULL
);
CREATE INDEX relation_uic_uic ON relation_uic(uic);
"""

_BATCH = 10_000


def build_store(
    pbf_path: str | os.PathLike,
    out_path: str | os.PathLike,
    region: str = "",
    source_date: str = "",
) -> dict:
    """Build the store for one region. Returns the stats written to ``meta``.

    Overwrites *out_path*: a store is a derived artifact, never edited in place.
    """
    import osmium  # noqa: PLC0415 — build-time only, see module docstring

    t0 = time.monotonic()
    out_path = str(out_path)
    if os.path.exists(out_path):
        os.remove(out_path)

    conn = sqlite3.connect(out_path)
    # No durability needed while building — a crashed build is thrown away and
    # rerun, and the fsync per transaction otherwise dominates the wall clock.
    conn.execute("PRAGMA journal_mode = OFF")
    conn.execute("PRAGMA synchronous = OFF")
    conn.executescript(_SCHEMA)

    ways: list[tuple] = []
    boxes: list[tuple] = []
    stations: list[tuple] = []
    station_boxes: list[tuple] = []
    relations: list[tuple] = []
    rel_ways: list[tuple] = []
    rel_uics: list[tuple] = []
    # Which ways the file actually holds: a relation names members the extract
    # does not carry, and a dangling row would make the store lie to anyone
    # reading it by hand.
    way_ids: set[int] = set()
    # Every node carrying a uic_ref, not just the station/halt ones: strategy A
    # asks Overpass for `node["uic_ref"=X]` with no railway filter, and in
    # practice route relations reference the stop_position node rather than the
    # station node (Luxembourg: 20 relation member nodes carry a uic_ref, none
    # of them tagged station or halt). Whether those nodes survive Phase 1's
    # filter is Phase 1's call; the builder uses them when they are there.
    node_uic: dict[int, str] = {}
    counts = {"ways": 0, "member_ways": 0, "nodes": 0, "stations": 0, "relations": 0}
    extent = [90.0, 180.0, -90.0, -180.0]  # min_lat, min_lon, max_lat, max_lon

    def flush() -> None:
        conn.executemany("INSERT INTO way VALUES (?, ?, ?)", ways)
        conn.executemany("INSERT INTO way_bbox VALUES (?, ?, ?, ?, ?)", boxes)
        ways.clear()
        boxes.clear()

    # Nodes, then ways, then relations — PBF order, so the station map is
    # complete by the time relations need it and one pass is enough.
    for obj in osmium.FileProcessor(str(pbf_path)).with_locations():
        tags = obj.tags
        if obj.is_node():
            uic = tags.get("uic_ref")
            if not uic:
                continue
            node_uic[obj.id] = clean_uic(uic)
            if tags.get("railway") in _STATION_VALUES:
                lat, lon = obj.location.lat, obj.location.lon
                stations.append((obj.id, lat, lon, uic))
                station_boxes.append((obj.id, lon, lon, lat, lat))
                counts["stations"] += 1
        elif obj.is_way():
            pts = [(n.lat, n.lon) for n in obj.nodes if n.location.valid()]
            if len(pts) < 2:
                continue
            is_rail = int(tags.get("railway") in _RAIL_VALUES and "service" not in tags)
            ways.append((obj.id, is_rail, encode_geometry(pts)))
            way_ids.add(obj.id)
            counts["nodes"] += len(pts)
            counts["ways" if is_rail else "member_ways"] += 1
            lats = [p[0] for p in pts]
            lons = [p[1] for p in pts]
            if is_rail:
                boxes.append((obj.id, min(lons), max(lons), min(lats), max(lats)))
                extent[0] = min(extent[0], min(lats))
                extent[1] = min(extent[1], min(lons))
                extent[2] = max(extent[2], max(lats))
                extent[3] = max(extent[3], max(lons))
            if len(ways) >= _BATCH:
                flush()
        else:
            if tags.get("route") not in _ROUTE_VALUES:
                continue
            relations.append((obj.id, tags["route"], tags.get("name")))
            counts["relations"] += 1
            seq = 0
            seen_uic = set()
            for member in obj.members:
                if member.type == "w" and member.ref in way_ids:
                    rel_ways.append((obj.id, member.ref, seq))
                    seq += 1
                elif member.type == "n":
                    uic = node_uic.get(member.ref)
                    if uic and uic not in seen_uic:
                        seen_uic.add(uic)
                        rel_uics.append((obj.id, uic))

    flush()
    conn.executemany("INSERT INTO station VALUES (?, ?, ?, ?)", stations)
    conn.executemany("INSERT INTO station_pos VALUES (?, ?, ?, ?, ?)", station_boxes)
    conn.executemany("INSERT INTO relation VALUES (?, ?, ?)", relations)
    conn.executemany("INSERT INTO relation_way VALUES (?, ?, ?)", rel_ways)
    conn.executemany("INSERT INTO relation_uic VALUES (?, ?)", rel_uics)

    stats = dict(counts)
    stats["build_seconds"] = round(time.monotonic() - t0, 2)
    meta = {
        "schema": str(SCHEMA_VERSION),
        "region": region,
        "source_file": os.path.basename(str(pbf_path)),
        "source_date": source_date,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "min_lat": repr(extent[0]),
        "min_lon": repr(extent[1]),
        "max_lat": repr(extent[2]),
        "max_lon": repr(extent[3]),
        **{k: str(v) for k, v in stats.items()},
    }
    conn.executemany("INSERT INTO meta VALUES (?, ?)", meta.items())
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
    conn.execute("VACUUM")   # the store ships over the network; give it no slack
    conn.close()

    stats["bytes"] = os.path.getsize(out_path)
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build a rail store from a filtered .osm.pbf")
    ap.add_argument("pbf")
    ap.add_argument("out")
    ap.add_argument("--region", default="", help='e.g. "europe/germany"')
    ap.add_argument("--source-date", default="", help="date of the source extract")
    args = ap.parse_args(argv)
    stats = build_store(args.pbf, args.out, args.region, args.source_date)
    print(" ".join(f"{k}={v}" for k, v in stats.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
