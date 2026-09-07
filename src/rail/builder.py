"""Build a per-region rail store from a filtered rail-only ``.osm.pbf``.

The input is Phase 1's artifact — the extract already reduced to the selection
table in docs/LOCAL_RAIL_DATA_PLAN.md (railway ways without ``service``, route
relations, every node carrying a ``uic_ref``, and station/halt nodes, ways and
relations with one). This module makes no tag decisions of its own beyond
recognising those, so changing coverage stays a Phase 1 concern.

Run it from Phase 1's pipeline (see the plan — building in CI, not on the box,
is Phase 2's decision and this is the step that implements it)::

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

from src.rail.store import SCHEMA_VERSION, encode_geometry

# The strategy-C way selection, repeated here only to tell track from a way that
# is in the file because something references it — a route relation's member, or
# a station polygon. Those keep their geometry but are not track the resolver
# may snap to or route over.
_RAIL_VALUES = {"rail", "narrow_gauge", "light_rail"}
_ROUTE_VALUES = {"train", "railway", "light_rail"}
_STATION_VALUES = {"station", "halt"}

_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

-- One row per way, geometry packed as int32 lat/lon pairs (see store.py).
-- rail=0 marks a way that is not track: a route relation's platform or service
-- member, or a station polygon. It keeps its geometry because the relation's
-- `out geom` includes it, but no rail query may return it.
CREATE TABLE way (
    id   INTEGER PRIMARY KEY,
    rail INTEGER NOT NULL,
    geom BLOB NOT NULL
);

-- Indexes every way, not just track: `relations_near` has to see a relation
-- whose nearby members are all platforms, exactly as Overpass's around: does.
-- Rail-only queries join `way` and filter on rail = 1.
CREATE VIRTUAL TABLE way_bbox USING rtree(id, min_lon, max_lon, min_lat, max_lat);

-- Stations mapped as nodes, ways or relations alike (Overpass's `out center`
-- returns a centre for all three, and polygon-mapped stations are common), so
-- `id` is ours and `osm_type`/`osm_id` say what it came from.
CREATE TABLE station (
    id       INTEGER PRIMARY KEY,
    osm_type TEXT NOT NULL,       -- node | way | relation
    osm_id   INTEGER NOT NULL,
    lat      REAL NOT NULL,
    lon      REAL NOT NULL,
    uic      TEXT NOT NULL        -- verbatim tag; Overpass matches it verbatim
);
CREATE VIRTUAL TABLE station_pos USING rtree(id, min_lon, max_lon, min_lat, max_lat);

CREATE TABLE relation (
    id    INTEGER PRIMARY KEY,
    route TEXT NOT NULL,
    name  TEXT
);
-- Every way member of the relation, in member order, whether or not the
-- extract holds that way: the reader joins to `way` and reports the members it
-- could not reconstruct rather than silently shortening the relation.
CREATE TABLE relation_way (
    rel_id INTEGER NOT NULL,
    way_id INTEGER NOT NULL,
    seq    INTEGER NOT NULL
);
CREATE INDEX relation_way_rel ON relation_way(rel_id);
CREATE INDEX relation_way_way ON relation_way(way_id);

-- Strategy A asks "which relation serves both these UIC codes". The uic is the
-- tag verbatim, because that is what Overpass compares against.
CREATE TABLE relation_uic (
    rel_id INTEGER NOT NULL,
    uic    TEXT NOT NULL
);
CREATE INDEX relation_uic_uic ON relation_uic(uic);
"""

_BATCH = 10_000


class RailBuildError(Exception):
    pass


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
    # Station relations resolve after the way pass: a multipolygon station's
    # centre is the centre of its members, and those are in the database by then.
    pending_rel_stations: list[tuple] = []
    # Which ways the file actually holds. Relation membership is recorded in
    # full even when a member is not held — a route relation names platforms and
    # service tracks that the way filter drops (Phase 1 measured 32% of
    # Denmark's route=train member ways falling outside it) — and a reader that
    # cannot tell "member we do not hold" from "not a member" has no way to
    # report a partially reconstructed relation.
    way_ids: set[int] = set()
    # Every node carrying a uic_ref, whatever else it is tagged: strategy A asks
    # Overpass for `node["uic_ref"=X]` with no railway filter, and route
    # relations reference the stop node rather than the station node.
    node_uic: dict[int, str] = {}
    counts = {
        "ways": 0, "member_ways": 0, "nodes": 0, "stations": 0, "relations": 0,
        "relation_ways": 0, "relation_ways_held": 0,
        # Nodes a way references that the extract does not locate. Dropping one
        # welds its neighbours together, which silently moves the geometry, so
        # the number is recorded rather than left to be guessed at.
        "ways_missing_nodes": 0, "missing_nodes": 0,
    }
    extent = [90.0, 180.0, -90.0, -180.0]  # min_lat, min_lon, max_lat, max_lon

    def flush() -> None:
        conn.executemany("INSERT INTO way VALUES (?, ?, ?)", ways)
        conn.executemany("INSERT INTO way_bbox VALUES (?, ?, ?, ?, ?)", boxes)
        ways.clear()
        boxes.clear()

    def add_station(osm_type: str, osm_id: int, lat: float, lon: float, uic: str) -> None:
        sid = len(stations) + 1
        stations.append((sid, osm_type, osm_id, lat, lon, uic))
        station_boxes.append((sid, lon, lon, lat, lat))
        counts["stations"] += 1

    # Nodes, then ways, then relations — PBF order, so the uic map is complete
    # by the time relations need it and one pass is enough.
    for obj in osmium.FileProcessor(str(pbf_path)).with_locations():
        tags = obj.tags
        uic = tags.get("uic_ref")
        is_station = bool(uic) and tags.get("railway") in _STATION_VALUES
        if obj.is_node():
            if not uic:
                continue
            node_uic[obj.id] = uic
            if is_station:
                add_station("node", obj.id, obj.location.lat, obj.location.lon, uic)
        elif obj.is_way():
            pts = [(n.lat, n.lon) for n in obj.nodes if n.location.valid()]
            missing = len(obj.nodes) - len(pts)
            if missing:
                counts["ways_missing_nodes"] += 1
                counts["missing_nodes"] += missing
            if len(pts) < 2:
                continue
            is_rail = int(tags.get("railway") in _RAIL_VALUES and "service" not in tags)
            ways.append((obj.id, is_rail, encode_geometry(pts)))
            way_ids.add(obj.id)
            counts["nodes"] += len(pts)
            counts["ways" if is_rail else "member_ways"] += 1
            lats = [p[0] for p in pts]
            lons = [p[1] for p in pts]
            box = (obj.id, min(lons), max(lons), min(lats), max(lats))
            boxes.append(box)
            if is_rail:
                extent[0] = min(extent[0], box[3])
                extent[1] = min(extent[1], box[1])
                extent[2] = max(extent[2], box[4])
                extent[3] = max(extent[3], box[2])
            if is_station:
                # Overpass's `out center` is the centre of the element's
                # bounding box, so a polygon station lands where Overpass puts it.
                add_station("way", obj.id, (box[3] + box[4]) / 2, (box[1] + box[2]) / 2, uic)
            if len(ways) >= _BATCH:
                flush()
        else:
            if is_station:
                pending_rel_stations.append(
                    (obj.id, uic, [m.ref for m in obj.members if m.type == "w"]))
            if tags.get("route") not in _ROUTE_VALUES:
                continue
            relations.append((obj.id, tags["route"], tags.get("name")))
            counts["relations"] += 1
            seq = 0
            seen_uic = set()
            for member in obj.members:
                if member.type == "w":
                    rel_ways.append((obj.id, member.ref, seq))
                    counts["relation_ways_held"] += member.ref in way_ids
                    seq += 1
                elif member.type == "n":
                    member_uic = node_uic.get(member.ref)
                    if member_uic and member_uic not in seen_uic:
                        seen_uic.add(member_uic)
                        rel_uics.append((obj.id, member_uic))

    flush()

    # Station relations: centre of the bounding box of the members we hold,
    # which is what `out center` reports for a relation.
    for rel_id, uic, member_ids in pending_rel_stations:
        box = _members_bbox(conn, member_ids)
        if box:
            add_station("relation", rel_id, (box[0] + box[2]) / 2, (box[1] + box[3]) / 2, uic)

    conn.executemany("INSERT INTO station VALUES (?, ?, ?, ?, ?, ?)", stations)
    conn.executemany("INSERT INTO station_pos VALUES (?, ?, ?, ?, ?)", station_boxes)
    conn.executemany("INSERT INTO relation VALUES (?, ?, ?)", relations)
    conn.executemany("INSERT INTO relation_way VALUES (?, ?, ?)", rel_ways)
    counts["relation_ways"] = len(rel_ways)
    conn.executemany("INSERT INTO relation_uic VALUES (?, ?)", rel_uics)

    if not counts["ways"]:
        # The region's extent comes from its track. With no track there is no
        # extent, and Phase 3 picks regions by extent — an inverted default box
        # would quietly claim to cover nothing, or everything, depending on the
        # comparison. Refuse to write a store that cannot answer "where am I".
        conn.close()
        os.remove(out_path)
        raise RailBuildError(f"{pbf_path}: no railway ways — not a rail extract")

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


def _members_bbox(conn: sqlite3.Connection, member_ids: list[int]) -> tuple | None:
    """(min_lat, min_lon, max_lat, max_lon) over the member ways we hold."""
    if not member_ids:
        return None
    rows = conn.execute(
        "SELECT min_lat, min_lon, max_lat, max_lon FROM way_bbox WHERE id IN "
        f"({','.join('?' * len(member_ids))})",
        member_ids,
    ).fetchall()
    if not rows:
        return None
    return (
        min(r[0] for r in rows), min(r[1] for r in rows),
        max(r[2] for r in rows), max(r[3] for r in rows),
    )


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
