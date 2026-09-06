"""Reader for a per-region rail store (issue #345, Phase 2).

One SQLite file per region, holding exactly what the three Overpass lookups in
``src/services/overpass_service.py`` return today:

  * the nearest station carrying a ``uic_ref``      (``_find_station_near``)
  * route relations covering two points             (strategies A and B)
  * railway ways inside a bounding box              (strategy C)

Element shapes match Overpass's ``out geom`` output for those queries, so
``_build_rail_graph`` and ``_extract_relation_geometry`` consume the store's
results unchanged. Phase 3 does that wiring; this module only serves lookups.

Why SQLite with R-tree indices rather than a loaded graph: the resolver never
needs a whole country at once — strategy C already works on a bounding box, and
a bbox query returns only the ways inside it. So the 319 MB Germany graph the
spike measured never has to exist. Resident memory is then the page cache of a
couple of open connections (``_CACHE_KIB``), not the size of a region, and
"which region is loaded" stops being a memory question. The file is also plain
SQLite: when a route looks wrong, the data behind it is one ``sqlite3`` session
away.

Coordinates are stored as 1e-7 degree fixed-point int32 pairs — OSM's own
precision, so the round trip is lossless — packed into one blob per way.
"""
from __future__ import annotations

import math
import os
import sqlite3
import sys
import threading
from array import array
from collections import OrderedDict
from typing import Iterable, Optional

# Bump when the schema changes shape; the reader refuses a store it cannot read
# rather than returning wrong geometry from a half-understood file.
SCHEMA_VERSION = 1

# Fixed-point scale for stored coordinates. 1e-7 degrees is OSM's own storage
# precision, so encode/decode loses nothing, and 180e7 still fits in an int32.
_COORD_SCALE = 1e7

_M_PER_DEG_LAT = 111_320.0

# Page cache per open connection. Two open regions then cost ~4 MB of cache
# regardless of how big those regions are — the ceiling the LRU test asserts.
_CACHE_KIB = 2048

# Radii tried in turn by nearest_node/nearest_station before giving up. Starting
# small keeps the common case (a stop sitting on the track) to one tiny R-tree
# hit; each step only runs when the previous one found nothing within itself.
_SEARCH_STEPS_M = (500.0, 2_000.0, 10_000.0)


class RailStoreError(Exception):
    pass


def store_filename(region: str) -> str:
    """File name for *region* ("europe/germany" -> "europe-germany.rail.sqlite").

    Shared with the builder so a store written for a region is found by it.
    """
    return region.strip("/").replace("/", "-") + ".rail.sqlite"


def encode_geometry(points: Iterable[tuple[float, float]]) -> bytes:
    """Pack (lat, lon) pairs into the stored blob format."""
    vals = array("i")
    for lat, lon in points:
        vals.append(int(round(lat * _COORD_SCALE)))
        vals.append(int(round(lon * _COORD_SCALE)))
    if sys.byteorder != "little":
        vals.byteswap()
    return vals.tobytes()


def decode_geometry(blob: bytes) -> list[dict]:
    """Unpack a stored blob into Overpass ``out geom`` vertices."""
    vals = array("i")
    vals.frombytes(blob)
    if sys.byteorder != "little":
        vals.byteswap()
    return [
        {"lat": vals[i] / _COORD_SCALE, "lon": vals[i + 1] / _COORD_SCALE}
        for i in range(0, len(vals), 2)
    ]


def clean_uic(uic: str) -> str:
    """Normalise a UIC code for matching.

    Mirrors ``overpass_service._clean_uic``: OSM and HAFAS disagree about
    leading zeros, so both sides of a comparison are stripped of them.
    """
    uic = (uic or "").strip()
    return uic.lstrip("0") or uic


def _dist_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Equirectangular metres — same approximation the resolver's Dijkstra uses."""
    dlat = (lat1 - lat2) * _M_PER_DEG_LAT
    dlon = (lon1 - lon2) * _M_PER_DEG_LAT * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


def _box(lat: float, lon: float, radius_m: float) -> tuple[float, float, float, float]:
    """(min_lat, min_lon, max_lat, max_lon) enclosing the radius circle."""
    dlat = radius_m / _M_PER_DEG_LAT
    # cos() floor keeps the box finite near the poles; rail there is a non-issue
    # but an infinite longitude span would break the R-tree query.
    dlon = radius_m / (_M_PER_DEG_LAT * max(math.cos(math.radians(lat)), 0.01))
    return lat - dlat, lon - dlon, lat + dlat, lon + dlon


class RailStore:
    """Read-only handle on one region's store file."""

    def __init__(self, path: str | os.PathLike) -> None:
        self.path = str(path)
        if not os.path.exists(self.path):
            raise RailStoreError(f"no rail store at {self.path}")
        # check_same_thread=False plus a lock: resolve jobs run on worker
        # threads, and a store is shared between them by the LRU below. SQLite
        # itself is fine with that, the Python connection object is not.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        self._conn.execute(f"PRAGMA cache_size = -{_CACHE_KIB}")
        self._conn.execute("PRAGMA query_only = 1")
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version != SCHEMA_VERSION:
            self._conn.close()
            raise RailStoreError(
                f"{self.path}: schema version {version}, expected {SCHEMA_VERSION}"
            )
        self.meta = {
            k: v for k, v in self._conn.execute("SELECT key, value FROM meta")
        }

    # ------------------------------------------------------------------
    # Region identity
    # ------------------------------------------------------------------

    @property
    def region(self) -> str:
        return self.meta.get("region", "")

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        """(min_lat, min_lon, max_lat, max_lon) actually covered by the data."""
        return (
            float(self.meta["min_lat"]),
            float(self.meta["min_lon"]),
            float(self.meta["max_lat"]),
            float(self.meta["max_lon"]),
        )

    # ------------------------------------------------------------------
    # Lookup 1 — nearest station with a uic_ref  (_find_station_near)
    # ------------------------------------------------------------------

    def nearest_station(self, lat: float, lon: float, radius_m: float = 5000) -> Optional[dict]:
        """Nearest station/halt with a ``uic_ref`` within *radius_m*, or None.

        Returns ``{"lat", "lon", "uic"}`` — what ``_enrich_uic`` consumes. Unlike
        the Overpass version this ranks by metres rather than by squared degrees,
        which only differs from it away from the equator, and only in favour of
        the geometrically nearer station.
        """
        min_lat, min_lon, max_lat, max_lon = _box(lat, lon, radius_m)
        rows = self._query(
            "SELECT s.lat, s.lon, s.uic FROM station_pos p JOIN station s ON s.id = p.id "
            "WHERE p.max_lon >= ? AND p.min_lon <= ? AND p.max_lat >= ? AND p.min_lat <= ?",
            (min_lon, max_lon, min_lat, max_lat),
        )
        best = None
        best_d = radius_m
        for slat, slon, uic in rows:
            d = _dist_m(lat, lon, slat, slon)
            if d <= best_d:
                best, best_d = {"lat": slat, "lon": slon, "uic": uic}, d
        return best

    # ------------------------------------------------------------------
    # Lookup 2 — route relations covering two points  (strategies A and B)
    # ------------------------------------------------------------------

    def relations_for_uic_pair(self, uic1: str, uic2: str) -> list[int]:
        """Relation ids whose member stations include both UIC codes.

        The local equivalent of strategy A's ``rel[route=train](bn.a)(bn.b)``.
        """
        a, b = clean_uic(uic1), clean_uic(uic2)
        if not a or not b:
            return []
        rows = self._query(
            "SELECT ra.rel_id FROM relation_uic ra JOIN relation_uic rb "
            "ON ra.rel_id = rb.rel_id WHERE ra.uic = ? AND rb.uic = ? ORDER BY ra.rel_id",
            (a, b),
        )
        return [r[0] for r in rows]

    def relations_near(self, lat: float, lon: float, radius_m: float = 25_000) -> set[int]:
        """Ids of route relations with a member way inside *radius_m*.

        Strategy B intersects this for the two endpoints. Overpass's
        ``(around:)`` also matches on member *nodes*; a relation with a station
        within 25 km but no track within 25 km does not occur in practice, and
        the way test is the cheaper index.
        """
        min_lat, min_lon, max_lat, max_lon = _box(lat, lon, radius_m)
        rows = self._query(
            "SELECT DISTINCT rw.rel_id FROM way_bbox b JOIN relation_way rw ON rw.way_id = b.id "
            "WHERE b.max_lon >= ? AND b.min_lon <= ? AND b.max_lat >= ? AND b.min_lat <= ?",
            (min_lon, max_lon, min_lat, max_lat),
        )
        return {r[0] for r in rows}

    def relation_geometry(self, rel_ids: Iterable[int]) -> list[dict]:
        """Relations in Overpass ``out geom`` shape, member ways in member order.

        ``_extract_relation_geometry`` reads ``members[].type`` and
        ``members[].geometry`` only; member nodes and roles are omitted because
        nothing consumes them.
        """
        out = []
        for rel_id in rel_ids:
            row = self._query(
                "SELECT route, name FROM relation WHERE id = ?", (rel_id,)
            )
            if not row:
                continue
            route, name = row[0]
            members = [
                {"type": "way", "ref": way_id, "geometry": decode_geometry(geom)}
                for way_id, geom in self._query(
                    "SELECT w.id, w.geom FROM relation_way rw JOIN way w ON w.id = rw.way_id "
                    "WHERE rw.rel_id = ? ORDER BY rw.seq",
                    (rel_id,),
                )
            ]
            tags = {"route": route}
            if name:
                tags["name"] = name
            out.append({"type": "relation", "id": rel_id, "tags": tags, "members": members})
        return out

    # ------------------------------------------------------------------
    # Lookup 3 — railway ways in a bounding box  (strategy C)
    # ------------------------------------------------------------------

    def ways_in_bbox(
        self, min_lat: float, min_lon: float, max_lat: float, max_lon: float
    ) -> list[dict]:
        """Ways whose extent overlaps the box, in ``_build_rail_graph``'s shape.

        Selection is by bounding box overlap, so a way that merely *spans* the
        box is included where Overpass would need a node inside it. That is a
        superset, and a superset is the safe direction: the graph gains a way
        the route may use, never loses one it needs.
        """
        rows = self._query(
            "SELECT w.id, w.geom FROM way_bbox b JOIN way w ON w.id = b.id "
            "WHERE b.max_lon >= ? AND b.min_lon <= ? AND b.max_lat >= ? AND b.min_lat <= ?",
            (min_lon, max_lon, min_lat, max_lat),
        )
        return [
            {"type": "way", "id": way_id, "geometry": decode_geometry(geom)}
            for way_id, geom in rows
        ]

    # ------------------------------------------------------------------
    # Snapping — the index that replaces the linear _nearest_node scan
    # ------------------------------------------------------------------

    def nearest_node(self, lat: float, lon: float, max_radius_m: float = 25_000) -> Optional[dict]:
        """Nearest vertex of any railway way, as ``{"lat", "lon", "way"}``.

        ``_nearest_node`` scans every node of the built graph — 1.43 s over
        Germany, twice per resolve. Here the R-tree bounds the scan to the ways
        near the point. The result is the *same* vertex: a vertex outside the
        search box is further away than any vertex found inside it, so the first
        radius that contains a candidate contains the winner.

        Coordinates come back at full precision, so a caller can form the
        ``"{lat:.6f},{lon:.6f}"`` id ``_build_rail_graph`` uses.
        """
        radii = [r for r in _SEARCH_STEPS_M if r < max_radius_m] + [max_radius_m]
        for radius in radii:
            min_lat, min_lon, max_lat, max_lon = _box(lat, lon, radius)
            rows = self._query(
                "SELECT w.id, w.geom FROM way_bbox b JOIN way w ON w.id = b.id "
                "WHERE b.max_lon >= ? AND b.min_lon <= ? AND b.max_lat >= ? AND b.min_lat <= ?",
                (min_lon, max_lon, min_lat, max_lat),
            )
            best = None
            best_d = radius
            for way_id, geom in rows:
                for pt in decode_geometry(geom):
                    d = _dist_m(lat, lon, pt["lat"], pt["lon"])
                    if d <= best_d:
                        best, best_d = {"lat": pt["lat"], "lon": pt["lon"], "way": way_id}, d
            if best is not None:
                return best
        return None

    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def __enter__(self) -> "RailStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def _query(self, sql: str, params: tuple) -> list[tuple]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()


class RailStoreCache:
    """LRU over open region stores.

    The bound is on *open files*, not on data: a store answers from disk, so an
    open region costs its connection's page cache and nothing else. Two is
    enough for the one case that needs more than one region at a time — a route
    crossing a border (Phase 3).
    """

    def __init__(self, directory: str | os.PathLike, max_open: int = 2) -> None:
        self.directory = str(directory)
        self.max_open = max_open
        self._open: "OrderedDict[str, RailStore]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, region: str) -> Optional[RailStore]:
        """Open store for *region*, or None when the region is not held.

        None is the "not covered" outcome Phase 0 requires callers to handle by
        falling back to Overpass — it is not an error.
        """
        with self._lock:
            store = self._open.get(region)
            if store is not None:
                self._open.move_to_end(region)
                return store
            path = os.path.join(self.directory, store_filename(region))
            if not os.path.exists(path):
                return None
            store = RailStore(path)
            self._open[region] = store
            # Eviction drops the reference; it does not close the store. A
            # resolve holds the store it was handed across several queries, and
            # a third region arriving on another thread must not close the file
            # out from under it. The connection closes when the last holder
            # lets go, which is what bounds the open files in practice.
            while len(self._open) > self.max_open:
                self._open.popitem(last=False)
            return store

    def close_all(self) -> None:
        with self._lock:
            while self._open:
                _, store = self._open.popitem()
                store.close()
