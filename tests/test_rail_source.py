"""Rail geometry read from local region stores (#345, Phase 3).

The phase substitutes the data source and changes nothing else, so the central
test here is parity: each strategy, run against a store built from the fixture
extract, returns the *same polyline* it returns against an Overpass response
carrying the same data. ``FixtureOverpass`` is that response — it answers the
resolver's real queries out of the fixture's tables with Overpass's own
semantics (a metric ``around:`` circle, a way selected by having a node inside
the bounding box), deliberately not by calling the reader under test.

Stores are real, built by ``src.rail.builder`` from real and synthetic extracts.
Only the network is mocked, because the network is the only thing this phase is
allowed to stop using.
"""
import json
import math
import os
import re
import sqlite3
from unittest.mock import Mock, patch

import pytest

from src.rail.builder import build_store
from src.rail.store import decode_geometry, store_filename
from src.services import overpass_service as ov
from src.services.rail_source import (
    LocalRailSource,
    MANIFEST_NAME,
    MANIFEST_SCHEMA,
    RailSourceError,
    RailSourceOverload,
    load_coverage,
)

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "rail", "luxembourg-rail.osm.pbf")
REGION = "europe/luxembourg"

# Real Luxembourg stations from the fixture. The first pair shares four route
# relations, which is what strategy A looks for; the third is far enough away
# for strategies B and C to have something to route.
LUX_GARE = {"lat": 49.5999681, "lon": 6.1342493, "uic": "8200100"}
HOLLERICH = {"lat": 49.5956799, "lon": 6.1201184, "uic": "8200710"}
KLEINBETTINGEN = {"lat": 49.6385071, "lon": 5.9823816, "uic": "8200518"}

_M_PER_DEG_LAT = 111_320.0


def _dist_m(lat1, lon1, lat2, lon2):
    dlat = (lat1 - lat2) * _M_PER_DEG_LAT
    dlon = (lon1 - lon2) * _M_PER_DEG_LAT * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


# ---------------------------------------------------------------------------
# Building the data a test needs
# ---------------------------------------------------------------------------

def write_manifest(directory, entries, schema=MANIFEST_SCHEMA):
    with open(os.path.join(directory, MANIFEST_NAME), "w", encoding="utf-8") as handle:
        json.dump({"schema": schema, "generated_at": "2026-09-06T18:00:00Z",
                   "regions": entries}, handle)


def ok_entry(region, bbox):
    """A published region. *bbox* is the store's (min_lat, min_lon, max_lat, max_lon).

    The manifest records it the other way round — Phase 1 writes
    ``[min_lon, min_lat, max_lon, max_lat]`` — and the transposition is a thing
    that can silently be got wrong, so the tests state it here once.
    """
    min_lat, min_lon, max_lat, max_lon = bbox
    return {"region": region, "status": "ok", "file": "x-rail.osm.pbf",
            "source": "https://example.invalid", "source_date": "2026-09-05",
            "sha256": "0" * 64, "bytes": 1, "ways": 1, "relations": 1, "stations": 1,
            "bbox": [min_lon, min_lat, max_lon, max_lat]}


def build_region(directory, region, pbf):
    """Build *pbf* into *directory* as *region*, returning its store bbox."""
    path = os.path.join(directory, store_filename(region))
    build_store(pbf, path, region=region, source_date="2026-09-05")
    conn = sqlite3.connect(path)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta"))
    finally:
        conn.close()
    return tuple(float(meta[k]) for k in ("min_lat", "min_lon", "max_lat", "max_lon"))


def write_extract(path, ways, stations=(), relations=()):
    """A minimal rail extract.

    *ways* maps way id to [(lat, lon), …]; *stations* is [(lat, lon, uic)];
    *relations* is [(rel_id, [member way ids])] — member ids the file does not
    hold are allowed, and are how a cross-border relation is expressed.
    """
    import osmium
    from osmium.osm import mutable

    writer = osmium.SimpleWriter(str(path))
    node_id = 1
    way_nodes = {}
    for way_id, points in ways.items():
        refs = []
        for lat, lon in points:
            writer.add_node(mutable.Node(id=node_id, location=(lon, lat)))
            refs.append(node_id)
            node_id += 1
        way_nodes[way_id] = refs
    for lat, lon, uic in stations:
        writer.add_node(mutable.Node(
            id=node_id, location=(lon, lat),
            tags={"railway": "station", "uic_ref": uic}))
        node_id += 1
    for way_id, refs in way_nodes.items():
        writer.add_way(mutable.Way(id=way_id, nodes=refs, tags={"railway": "rail"}))
    for rel_id, members in relations:
        writer.add_relation(mutable.Relation(
            id=rel_id, members=[("w", m, "") for m in members],
            tags={"route": "train", "name": f"Relation {rel_id}"}))
    writer.close()


# ---------------------------------------------------------------------------
# The oracle: what Overpass would answer, given this extract's data
# ---------------------------------------------------------------------------

class FixtureOverpass:
    """A stand-in for ``_overpass`` that answers out of a store's tables.

    It reads the tables with its own SQL and its own geometry maths rather than
    through ``RailStore``, so a bug in the reader or in the region merging shows
    up as a difference rather than cancelling out on both sides. Overpass's
    semantics, not the store's: ``around:`` is a circle in metres, and a
    bounding box selects a way that has a *node* inside it, where the store
    accepts any way whose extent overlaps.
    """

    def __init__(self, path):
        self.conn = sqlite3.connect(path)
        self.queries = []

    def __call__(self, query):
        self.queries.append(query)
        if '"railway"~"^(station|halt)$"' in query:
            return {"elements": self._stations(*self._around(query))}
        if 'node["uic_ref"="' in query:
            uic1, uic2 = re.findall(r'node\["uic_ref"="([^"]*)"\]', query)
            return {"elements": self._relations(self._pair_ids(uic1, uic2))}
        if "out ids" in query:
            return {"elements": [{"type": "relation", "id": rel_id}
                                 for rel_id in self._near_ids(*self._around(query))]}
        if "rel(id:" in query:
            ids = [int(i) for i in
                   re.search(r"rel\(id:([\d,]+)\)", query).group(1).split(",")]
            return {"elements": self._relations(ids)}
        if 'way["railway"' in query:
            box = [float(v) for v in
                   re.search(r"\(([-\d.,]+)\);", query).group(1).split(",")]
            return {"elements": self._ways(*box)}
        raise AssertionError(f"unrecognised query: {query}")

    @staticmethod
    def _around(query):
        radius, lat, lon = re.search(
            r"around:([\d.]+),([-\d.]+),([-\d.]+)", query).groups()
        return float(radius), float(lat), float(lon)

    def _stations(self, radius, lat, lon):
        out = []
        for osm_type, slat, slon, uic in self.conn.execute(
                "SELECT osm_type, lat, lon, uic FROM station"):
            if _dist_m(lat, lon, slat, slon) > radius:
                continue
            element = {"type": osm_type, "tags": {"uic_ref": uic}}
            if osm_type == "node":
                element.update(lat=slat, lon=slon)
            else:
                element["center"] = {"lat": slat, "lon": slon}
            out.append(element)
        return out

    def _pair_ids(self, uic1, uic2):
        return [row[0] for row in self.conn.execute(
            "SELECT a.rel_id FROM relation_uic a JOIN relation_uic b "
            "ON a.rel_id = b.rel_id WHERE a.uic = ? AND b.uic = ? ORDER BY a.rel_id",
            (uic1, uic2))]

    def _near_ids(self, radius, lat, lon):
        found = set()
        for rel_id, geom in self.conn.execute(
                "SELECT rw.rel_id, w.geom FROM relation_way rw "
                "JOIN way w ON w.id = rw.way_id"):
            if rel_id in found:
                continue
            if any(_dist_m(lat, lon, p["lat"], p["lon"]) <= radius
                   for p in decode_geometry(geom)):
                found.add(rel_id)
        return sorted(found)

    def _relations(self, rel_ids):
        out = []
        for rel_id in rel_ids:
            row = self.conn.execute(
                "SELECT route, name FROM relation WHERE id = ?", (rel_id,)).fetchone()
            if row is None:
                continue
            members = [
                {"type": "way", "ref": way_id,
                 "geometry": decode_geometry(geom) if geom is not None else []}
                for way_id, geom in self.conn.execute(
                    "SELECT rw.way_id, w.geom FROM relation_way rw LEFT JOIN way w "
                    "ON w.id = rw.way_id WHERE rw.rel_id = ? ORDER BY rw.seq", (rel_id,))
            ]
            tags = {"route": row[0]}
            if row[1]:
                tags["name"] = row[1]
            out.append({"type": "relation", "id": rel_id, "tags": tags,
                        "members": members})
        return out

    def _ways(self, min_lat, min_lon, max_lat, max_lon):
        out = []
        for way_id, geom in self.conn.execute(
                "SELECT id, geom FROM way WHERE rail = 1 ORDER BY id"):
            points = decode_geometry(geom)
            if any(min_lat <= p["lat"] <= max_lat and min_lon <= p["lon"] <= max_lon
                   for p in points):
                out.append({"type": "way", "id": way_id, "geometry": points})
        return out


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _forget_configured_source():
    """The configured source is cached per directory; each test gets its own."""
    ov._local_source = None
    yield
    ov._local_source = None


@pytest.fixture(scope="module")
def lux_dir(tmp_path_factory):
    """A data directory holding the Luxembourg fixture as a built region."""
    directory = str(tmp_path_factory.mktemp("raildata"))
    bbox = build_region(directory, REGION, FIXTURE)
    write_manifest(directory, [ok_entry(REGION, bbox)])
    return directory


@pytest.fixture(scope="module")
def local(lux_dir):
    return LocalRailSource(lux_dir)


@pytest.fixture
def oracle(lux_dir):
    return FixtureOverpass(os.path.join(lux_dir, store_filename(REGION)))


# ---------------------------------------------------------------------------
# Parity — the point of the phase
# ---------------------------------------------------------------------------

class TestSameGeometryAsOverpass:
    """Same data, same polyline, whichever source it came through."""

    def test_station_lookup(self, local, oracle):
        with patch.object(ov, "_overpass", side_effect=oracle):
            over = ov._find_station_near(49.601, 6.130)
        assert over is not None
        assert ov._find_station_near(49.601, 6.130, source=local) == over

    def test_strategy_a_uic_relations(self, local, oracle):
        stops = [LUX_GARE, HOLLERICH]
        with patch.object(ov, "_overpass", side_effect=oracle):
            over = ov._via_route_relations(stops)
        assert len(over) > 10          # a real path, not a two-point stub
        assert ov._via_route_relations(stops, local) == over

    def test_strategy_b_endpoint_relations(self, local, oracle):
        stops = [LUX_GARE, KLEINBETTINGEN]
        with patch.object(ov, "_overpass", side_effect=oracle):
            over = ov._via_train_relations_endpoints(stops)
        assert len(over) > 10
        assert ov._via_train_relations_endpoints(stops, local) == over

    def test_strategy_c_coordinate_dijkstra(self, local, oracle):
        stops = [LUX_GARE, KLEINBETTINGEN]
        with patch.object(ov, "_overpass", side_effect=oracle):
            over = ov._via_coordinate_fallback(stops)
        assert len(over) > 10
        assert ov._via_coordinate_fallback(stops, local) == over

    def test_whole_resolve(self, lux_dir, oracle, monkeypatch):
        """End to end, through get_rail_geometry's own strategy selection."""
        stops = [dict(LUX_GARE), dict(KLEINBETTINGEN)]
        with patch.object(ov, "_overpass", side_effect=oracle):
            over = ov.get_rail_geometry(stops)

        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.setenv("RAIL_DATA_DIR", lux_dir)
        transport = Mock(name="_overpass")
        with patch.object(ov, "_overpass", transport):
            locally = ov.get_rail_geometry(stops)

        assert not over.degraded
        assert (locally.polyline, locally.strategy, locally.degraded) == (
            over.polyline, over.strategy, over.degraded)
        assert transport.call_count == 0, "a local hit must not touch the network"


# ---------------------------------------------------------------------------
# Overlapping regions — the data picks the region, not the geometry
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def two_regions(tmp_path_factory):
    """Two regions whose boxes both cover the same points.

    Both hold a line spanning the same longitudes, so neither box can be
    preferred over the other by geometry. What differs is the data: each has its
    own station, and way 100 is in both files — as a real border way is, because
    Geofabrik's extracts overlap.
    """
    directory = str(tmp_path_factory.mktemp("tworegions"))
    shared = {100: [(49.60, 5.90), (49.60, 6.30)]}
    west = tmp_path_factory.mktemp("west") / "west-rail.osm.pbf"
    east = tmp_path_factory.mktemp("east") / "east-rail.osm.pbf"
    # The two stations are 2.9 km apart — inside each other's 5 km search
    # radius, so both regions really do answer and the nearer one has to win on
    # distance rather than on which region happened to be read first.
    write_extract(west, {**shared, 101: [(49.61, 6.00), (49.61, 6.02)]},
                  stations=[(49.600, 6.010, "1000")])
    write_extract(east, {**shared, 102: [(49.61, 6.09), (49.61, 6.11)]},
                  stations=[(49.600, 6.050, "2000")])
    entries = [ok_entry("test/west", build_region(directory, "test/west", west)),
               ok_entry("test/east", build_region(directory, "test/east", east))]
    write_manifest(directory, entries)
    return directory


class TestOverlappingRegions:
    def test_both_regions_are_candidates(self, two_regions):
        source = LocalRailSource(two_regions)
        assert source.regions_for((49.60, 6.02, 49.60, 6.02)) == [
            "test/east", "test/west"]

    def test_nearest_station_comes_from_whichever_region_holds_it(self, two_regions):
        source = LocalRailSource(two_regions)
        # Same pair of candidate regions both times, and both regions answer
        # both times; only which answer is nearer differs.
        assert source.nearest_station(49.600, 6.020)["uic"] == "1000"
        assert source.nearest_station(49.600, 6.045)["uic"] == "2000"

    def test_bbox_query_merges_both_regions_and_deduplicates_by_way_id(
            self, two_regions):
        source = LocalRailSource(two_regions)
        ways = source.ways_in_bbox(49.5, 5.8, 49.7, 6.4)
        assert [w["id"] for w in ways] == [100, 101, 102], (
            "a cross-border box must see both regions' track, and the way both "
            "extracts hold exactly once")
        # The shared way keeps its geometry rather than being merged into a stub.
        assert ways[0]["geometry"] == [{"lat": 49.60, "lon": 5.90},
                                       {"lat": 49.60, "lon": 6.30}]

    def test_a_relation_is_reassembled_from_both_sides_of_the_border(
            self, tmp_path_factory):
        """The gap Phase 1 cannot close from one file: a relation's member ways
        live in whichever country they run through. Overpass returns all of
        them, so the local source has to put the halves back together."""
        directory = str(tmp_path_factory.mktemp("crossborder"))
        west = tmp_path_factory.mktemp("cbw") / "west-rail.osm.pbf"
        east = tmp_path_factory.mktemp("cbe") / "east-rail.osm.pbf"
        # 500 crosses the border and is in both files. 501 and 502 run on one
        # side each, so neither region's answer alone is the whole answer.
        write_extract(west, {10: [(49.60, 6.00), (49.60, 6.05)]},
                      relations=[(500, [10, 11]), (502, [10])])
        write_extract(east, {11: [(49.60, 6.05), (49.60, 6.10)]},
                      relations=[(500, [10, 11]), (501, [11])])
        entries = [ok_entry("test/west", build_region(directory, "test/west", west)),
                   ok_entry("test/east", build_region(directory, "test/east", east))]
        write_manifest(directory, entries)
        source = LocalRailSource(directory)

        # Strategy B intersects the two endpoints' sets, so a set from one
        # region only would drop a relation at exactly the border.
        assert source.relations_near(49.60, 6.05) == {500, 501, 502}

        relations = source.relation_geometry([500], [(49.60, 6.00), (49.60, 6.10)])
        assert len(relations) == 1
        assert relations[0]["missing_members"] == 0
        assert [m["ref"] for m in relations[0]["members"]] == [10, 11]
        assert all(len(m["geometry"]) == 2 for m in relations[0]["members"])


# ---------------------------------------------------------------------------
# Coverage — every way of not covering a point ends in the same place
# ---------------------------------------------------------------------------

class TestCoverage:
    def test_no_data_directory(self, tmp_path):
        source = LocalRailSource(tmp_path / "nothing-here")
        assert source.coverage == []
        assert source.nearest_station(49.60, 6.13) is None

    def test_no_manifest(self, tmp_path):
        assert load_coverage(str(tmp_path)) == []

    def test_unknown_schema_is_refused_rather_than_read(self, tmp_path):
        write_manifest(str(tmp_path), [ok_entry(REGION, (49.0, 5.0, 51.0, 7.0))],
                       schema=MANIFEST_SCHEMA + 1)
        with pytest.raises(RailSourceError, match="schema"):
            LocalRailSource(str(tmp_path))

    def test_unparseable_manifest_is_refused(self, tmp_path):
        (tmp_path / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
        with pytest.raises(RailSourceError):
            LocalRailSource(str(tmp_path))

    def test_empty_region_is_accounted_for_but_not_covered(self, tmp_path):
        """`empty` means "we know there is no rail here" — an answer, not a gap,
        and still not something to route on."""
        write_manifest(str(tmp_path), [
            {"region": "europe/andorra", "status": "empty",
             "source": "https://example.invalid", "source_date": "2026-09-05"},
            ok_entry(REGION, (49.0, 5.0, 51.0, 7.0)),
        ])
        assert [r for r, _ in load_coverage(str(tmp_path))] == [REGION]

    def test_region_whose_store_file_is_absent_is_skipped(self, tmp_path, caplog):
        write_manifest(str(tmp_path), [ok_entry(REGION, (49.0, 5.0, 51.0, 7.0))])
        source = LocalRailSource(str(tmp_path))
        assert source.regions_for((49.6, 6.1, 49.6, 6.1)) == [REGION]
        assert source.nearest_station(49.60, 6.13) is None
        assert source.ways_in_bbox(49.5, 6.0, 49.7, 6.2) == []

    def test_coordinate_outside_every_region(self, local):
        # Helsinki: covered by no European region this directory holds.
        assert local.regions_for((60.17, 24.94, 60.17, 24.94)) == []
        assert local.nearest_station(60.172097, 24.941249) is None
        assert local.relations_near(60.172097, 24.941249) == set()
        assert local.ways_in_bbox(60.0, 24.8, 60.3, 25.1) == []


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class TestConfiguration:
    def test_default_is_overpass_only(self, lux_dir, monkeypatch, oracle):
        """Unset config must leave the resolver exactly as it was: no store is
        opened even with a data directory sitting right there."""
        monkeypatch.delenv("RAIL_SOURCE", raising=False)
        monkeypatch.setenv("RAIL_DATA_DIR", lux_dir)
        assert ov._local_rail_source() is None

        stops = [dict(LUX_GARE), dict(KLEINBETTINGEN)]
        with patch.object(ov, "_overpass", side_effect=oracle):
            result = ov.get_rail_geometry(stops)
        assert not result.degraded
        assert oracle.queries, "the default path must still ask Overpass"

    def test_local_without_a_directory_stays_on_overpass(self, monkeypatch, caplog):
        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.delenv("RAIL_DATA_DIR", raising=False)
        assert ov._local_rail_source() is None

    def test_unusable_manifest_stays_on_overpass(self, tmp_path, monkeypatch):
        (tmp_path / MANIFEST_NAME).write_text("{not json", encoding="utf-8")
        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.setenv("RAIL_DATA_DIR", str(tmp_path))
        assert ov._local_rail_source() is None

    def test_local_is_selected_when_configured(self, lux_dir, monkeypatch):
        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.setenv("RAIL_DATA_DIR", lux_dir)
        source = ov._local_rail_source()
        assert isinstance(source, LocalRailSource)
        # Cached: reading the manifest and reopening the region files per resolve
        # would make the store cache pointless.
        assert ov._local_rail_source() is source


# ---------------------------------------------------------------------------
# Falling back
# ---------------------------------------------------------------------------

class TestOverpassFallback:
    def test_a_local_miss_resolves_via_overpass(self, tmp_path, monkeypatch):
        """A region can be held and hold almost nothing (Cyprus: two rail ways),
        so "the store said nothing" must not become a straight line."""
        write_manifest(str(tmp_path), [])
        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.setenv("RAIL_DATA_DIR", str(tmp_path))

        relation = {"type": "relation", "id": 7, "members": [{"type": "way", "geometry": [
            {"lat": 49.5999681, "lon": 6.1342493},
            {"lat": 49.62, "lon": 6.05},
            {"lat": 49.6385071, "lon": 5.9823816}]}]}

        def _answer(query):
            if "uic_ref" in query and "railway" in query:
                return {"elements": []}
            if "out ids" in query:
                return {"elements": [{"id": 7}]}
            return {"elements": [relation]}

        stops = [{"lat": LUX_GARE["lat"], "lon": LUX_GARE["lon"]},
                 {"lat": KLEINBETTINGEN["lat"], "lon": KLEINBETTINGEN["lon"]}]
        with patch.object(ov, "_overpass", side_effect=_answer):
            result = ov.get_rail_geometry(stops)

        assert result.strategy == "relation_endpoints"
        assert result.degraded is False

    def test_a_refused_bounding_box_does_not_become_an_overpass_query(
            self, lux_dir, monkeypatch):
        """The vertex ceiling bounds *our* memory. Overpass answering the same
        question rebuilds the allocation that was just refused, so a ceiling hit
        straight-lines instead of falling back."""
        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.setenv("RAIL_DATA_DIR", lux_dir)
        monkeypatch.setattr("src.services.rail_source._MAX_BBOX_VERTICES", 10)

        # Neither stop is near a station, so strategy A has no UIC codes, and
        # the second has no route relation within 25 km, so strategy B finds
        # nothing: the resolve reaches strategy C and its bounding box.
        stops = [{"lat": 49.50, "lon": 6.20}, {"lat": 50.17, "lon": 6.50}]
        transport = Mock(name="_overpass")
        with patch.object(ov, "_overpass", transport):
            result = ov.get_rail_geometry(stops)

        assert result.strategy == "straight"
        assert result.degraded is True
        assert result.polyline == [[6.20, 49.50], [6.50, 50.17]]
        assert transport.call_count == 0

    def test_the_ceiling_applies_to_the_merged_result(self, two_regions, monkeypatch):
        """Regions are merged, so the budget is shared: four regions must not
        together allocate what one of them would be refused."""
        source = LocalRailSource(two_regions)
        # Each region alone holds 4 vertices in this box; together they hold 6.
        monkeypatch.setattr("src.services.rail_source._MAX_BBOX_VERTICES", 5)
        with pytest.raises(RailSourceOverload):
            source.ways_in_bbox(49.5, 5.8, 49.7, 6.4)

    def test_the_ceiling_counts_a_shared_way_once(self, two_regions, monkeypatch):
        """…and counts what is *kept*, not what each region offered.

        Overlapping regions hold the same border ways, so summing their raw
        totals double-counts exactly where D-A's merging is the point. The
        merged result here is 6 vertices and the raw totals sum to 8; at a
        ceiling of 6 the query fits and must be answered. Charging the raw
        totals degrades the effective ceiling towards _MAX_BBOX_VERTICES / N,
        and an overload straight-lines with no fallback — so the symptom is a
        silent straight line on a cross-border route.
        """
        source = LocalRailSource(two_regions)
        monkeypatch.setattr("src.services.rail_source._MAX_BBOX_VERTICES", 6)
        ways = source.ways_in_bbox(49.5, 5.8, 49.7, 6.4)
        assert [w["id"] for w in ways] == [100, 101, 102]


# ---------------------------------------------------------------------------
# Broken local data — every shape of it defers to Overpass
# ---------------------------------------------------------------------------

def _corrupt_store(path, state):
    """Write a store file that exists and cannot be read, in *state*."""
    if state == "garbage":
        # A partial download: the bytes that arrived are not a database.
        path.write_bytes(b"\x1f\x8b\x08\x00 not a sqlite file at all")
    elif state == "zero_byte":
        # `touch`, or a download that got the file created and nothing else.
        path.write_bytes(b"")
    elif state == "wrong_schema":
        # A store built by a future (or past) builder.
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA user_version = 99")
        conn.close()
    else:  # pragma: no cover - test wiring
        raise AssertionError(state)


class TestUnreadableStoreFile:
    """A file the manifest names, that is present and cannot be opened.

    ``store.py`` already answers "the manifest names a file the directory does
    not hold" with None. A file that is *there* and broken raises instead, and
    every raise on this path escapes into the resolve job's retry — where the
    file is still broken, so the segment never resolves at all. A local problem
    must defer to Overpass, whatever shape it takes.
    """

    @pytest.fixture(params=["garbage", "zero_byte", "wrong_schema"])
    def broken_dir(self, request, tmp_path):
        _corrupt_store(tmp_path / store_filename(REGION), request.param)
        write_manifest(str(tmp_path), [ok_entry(REGION, (49.0, 5.0, 51.0, 7.0))])
        return str(tmp_path)

    def test_every_query_reads_as_not_covered(self, broken_dir):
        source = LocalRailSource(broken_dir)
        # The region is still coverage on paper — the manifest says so.
        assert source.regions_for((49.6, 6.1, 49.6, 6.1)) == [REGION]
        # …and every question about it answers "nothing here", not an exception.
        assert source.nearest_station(49.5999681, 6.1342493) is None
        assert source.relations_near(49.5999681, 6.1342493) == set()
        assert source.relations_for_uic_pair(
            "8200100", "8200710", [(49.60, 6.13), (49.64, 5.98)]) == []
        assert source.relation_geometry([1], [(49.60, 6.13), (49.64, 5.98)]) == []
        assert source.ways_in_bbox(49.5, 6.0, 49.7, 6.2) == []

    def test_the_resolve_falls_back_to_overpass_instead_of_failing(
            self, broken_dir, monkeypatch, oracle):
        """The whole point: a broken file costs Overpass traffic, not the route.

        Without this, the exception escapes ``get_rail_geometry`` into
        ``_resolve_route_job``'s retry, and the file is still broken on retry —
        so every train resolve in the deployment fails while it exists.
        """
        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.setenv("RAIL_DATA_DIR", broken_dir)
        stops = [dict(LUX_GARE), dict(KLEINBETTINGEN)]
        with patch.object(ov, "_overpass", side_effect=oracle):
            result = ov.get_rail_geometry(stops)
        assert not result.degraded
        assert oracle.queries, "a broken store must send the resolve to Overpass"


class TestMalformedManifest:
    """Every way the manifest can be wrong ends on Overpass, not in a traceback.

    ``_local_rail_source`` is the only caller, and "we cannot read the local
    data" has exactly one safe answer regardless of which builtin the reading
    happened to raise.
    """

    SHAPES = {
        "invalid_json": "{not json",
        "wrong_schema": '{"schema": 99, "regions": []}',
        "entry_without_region":
            '{"schema": 2, "regions": [{"status": "ok", "bbox": [5, 49, 7, 51]}]}',
        "non_numeric_bbox":
            '{"schema": 2, "regions": [{"region": "a", "status": "ok",'
            ' "bbox": ["west", 49, 7, 51]}]}',
        "regions_not_dicts": '{"schema": 2, "regions": ["europe/luxembourg"]}',
        "top_level_list": '[{"region": "europe/luxembourg"}]',
        "top_level_number": '42',
    }

    @pytest.fixture(params=sorted(SHAPES))
    def bad_dir(self, request, tmp_path):
        (tmp_path / MANIFEST_NAME).write_text(
            self.SHAPES[request.param], encoding="utf-8")
        return str(tmp_path)

    def test_stays_on_overpass(self, bad_dir, monkeypatch):
        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.setenv("RAIL_DATA_DIR", bad_dir)
        assert ov._local_rail_source() is None

    def test_the_resolve_still_produces_a_route(self, bad_dir, monkeypatch, oracle):
        monkeypatch.setenv("RAIL_SOURCE", "local")
        monkeypatch.setenv("RAIL_DATA_DIR", bad_dir)
        stops = [dict(LUX_GARE), dict(KLEINBETTINGEN)]
        with patch.object(ov, "_overpass", side_effect=oracle):
            result = ov.get_rail_geometry(stops)
        assert not result.degraded
        assert oracle.queries
