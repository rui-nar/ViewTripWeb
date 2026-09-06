"""Local rail store — build, read, index correctness and resource bounds (#345).

The fixture is a real rail-only extract of Luxembourg, cut with the tag
selection Phase 1 publishes; see ``tests/fixtures/rail/README.md``. A synthetic
two-station extract covers the relation lookups that depend on how a country's
mappers wired their relations, which no real extract can be relied on to have.
"""
import os
import random
import shutil
import sqlite3
import time
import tracemalloc

import pytest

from src.rail.builder import build_store
from src.rail.store import (
    RailStore,
    RailStoreCache,
    RailStoreError,
    _dist_m,
    decode_geometry,
    encode_geometry,
    store_filename,
)
from src.services.overpass_service import _build_rail_graph, _extract_relation_geometry

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "rail", "luxembourg-rail.osm.pbf")
REGION = "europe/luxembourg"


@pytest.fixture(scope="module")
def store_path(tmp_path_factory):
    out = tmp_path_factory.mktemp("railstore") / store_filename(REGION)
    build_store(FIXTURE, out, region=REGION, source_date="2026-09-05")
    return str(out)


@pytest.fixture(scope="module")
def store(store_path):
    with RailStore(store_path) as s:
        yield s


def _all_rail_vertices(path):
    """Every vertex of every rail way, read straight out of the tables.

    The brute-force oracle the R-tree queries are checked against — deliberately
    sharing no code with them.
    """
    conn = sqlite3.connect(path)
    pts = []
    for (geom,) in conn.execute("SELECT geom FROM way WHERE rail = 1"):
        pts.extend((p["lat"], p["lon"]) for p in decode_geometry(geom))
    conn.close()
    return pts


# ---------------------------------------------------------------------------
# Round trip: extract -> store -> the shapes the resolver already consumes
# ---------------------------------------------------------------------------

def test_store_holds_the_three_kinds_of_data_the_resolver_asks_for(store):
    assert int(store.meta["ways"]) == 1167
    assert int(store.meta["stations"]) == 66
    assert int(store.meta["relations"]) == 109
    assert store.region == REGION
    assert store.meta["source_date"] == "2026-09-05"
    min_lat, min_lon, max_lat, max_lon = store.bbox
    assert 49 < min_lat < max_lat < 51 and 5 < min_lon < max_lon < 7


def test_bbox_ways_build_the_same_graph_as_overpass_elements(store):
    min_lat, min_lon, max_lat, max_lon = store.bbox
    ways = store.ways_in_bbox(min_lat, min_lon, max_lat, max_lon)
    assert len(ways) == 1167
    for way in ways:
        assert len(way["geometry"]) >= 2
        assert set(way["geometry"][0]) == {"lat", "lon"}

    # The point of the shape contract: _build_rail_graph is unchanged by Phase 2.
    nodes, adj = _build_rail_graph(ways)
    assert len(nodes) > 10_000
    # Every adjacency entry names a node that exists — a malformed geometry list
    # would surface here rather than deep inside a Dijkstra run.
    assert all(n in nodes for neighbours in adj.values() for n in neighbours)


def test_bbox_selection_is_bounded_by_the_box(store):
    min_lat, min_lon, max_lat, max_lon = store.bbox
    mid_lat = (min_lat + max_lat) / 2
    half = store.ways_in_bbox(min_lat, min_lon, mid_lat, max_lon)
    whole = store.ways_in_bbox(min_lat, min_lon, max_lat, max_lon)
    assert 0 < len(half) < len(whole)
    assert {w["id"] for w in half} <= {w["id"] for w in whole}
    # Every way returned really does reach into the box.
    for way in half:
        assert any(min_lat <= p["lat"] <= mid_lat for p in way["geometry"])


def test_geometry_round_trips_at_osm_precision():
    pts = [(49.6001234, 6.1339999), (-33.8688, 151.2093), (0.0, 0.0)]
    out = decode_geometry(encode_geometry(pts))
    for (lat, lon), got in zip(pts, out):
        assert got["lat"] == pytest.approx(lat, abs=1e-7)
        assert got["lon"] == pytest.approx(lon, abs=1e-7)


def test_relation_geometry_feeds_extract_relation_geometry(store):
    conn = sqlite3.connect(store.path)
    rel_id = conn.execute(
        "SELECT rel_id FROM relation_way GROUP BY rel_id "
        "ORDER BY COUNT(*) DESC LIMIT 1").fetchone()[0]
    conn.close()

    rels = store.relation_geometry([rel_id])
    assert len(rels) == 1
    rel = rels[0]
    assert rel["tags"]["route"] in {"train", "railway", "light_rail"}
    assert all(m["type"] == "way" and len(m["geometry"]) >= 2 for m in rel["members"])

    # Consumed by the existing strategy-A/B code path without adaptation. A
    # disconnected relation legitimately yields None; it must not raise.
    geom = rel["members"][0]["geometry"]
    _extract_relation_geometry(
        rel, geom[0]["lat"], geom[0]["lon"], geom[-1]["lat"], geom[-1]["lon"])

    assert store.relation_geometry([-1]) == []


def test_ways_carried_only_for_a_relation_stay_out_of_spatial_results(store):
    """A way present because a relation references it has geometry but is not
    track: it must never be snapped to, routed over, or returned by a bbox
    query — while a relation's own geometry still includes it."""
    conn = sqlite3.connect(store.path)
    member_only = conn.execute("SELECT COUNT(*) FROM way WHERE rail = 0").fetchone()[0]
    indexed = conn.execute("SELECT COUNT(*) FROM way_bbox").fetchone()[0]
    rail = conn.execute("SELECT COUNT(*) FROM way WHERE rail = 1").fetchone()[0]
    conn.close()
    assert member_only > 0
    assert indexed == rail


# ---------------------------------------------------------------------------
# Spatial index correctness — against brute force
# ---------------------------------------------------------------------------

def test_nearest_node_matches_brute_force(store):
    points = _all_rail_vertices(store.path)
    min_lat, min_lon, max_lat, max_lon = store.bbox
    rng = random.Random(20260906)
    checked = 0
    for _ in range(40):
        lat = rng.uniform(min_lat, max_lat)
        lon = rng.uniform(min_lon, max_lon)
        want = min(points, key=lambda p: _dist_m(lat, lon, p[0], p[1]))
        want_d = _dist_m(lat, lon, want[0], want[1])
        got = store.nearest_node(lat, lon)
        if got is None:
            assert want_d > 25_000   # only allowed beyond the search ceiling
            continue
        got_d = _dist_m(lat, lon, got["lat"], got["lon"])
        assert got_d == pytest.approx(want_d, abs=1e-6)
        checked += 1
    assert checked >= 35


def test_nearest_node_on_a_vertex_returns_that_vertex(store):
    points = _all_rail_vertices(store.path)
    for lat, lon in points[:: max(1, len(points) // 20)]:
        got = store.nearest_node(lat, lon)
        assert got["lat"] == pytest.approx(lat, abs=1e-7)
        assert got["lon"] == pytest.approx(lon, abs=1e-7)


def test_nearest_node_gives_up_rather_than_snapping_across_a_continent(store):
    assert store.nearest_node(48.85, 2.35) is None            # Paris, 250 km away
    assert store.nearest_node(48.85, 2.35, max_radius_m=400_000) is not None


def test_nearest_station_matches_brute_force_and_honours_the_radius(store):
    conn = sqlite3.connect(store.path)
    stations = conn.execute("SELECT lat, lon, uic FROM station").fetchall()
    conn.close()

    rng = random.Random(7)
    for _ in range(25):
        base = rng.choice(stations)
        lat = base[0] + rng.uniform(-0.02, 0.02)
        lon = base[1] + rng.uniform(-0.02, 0.02)
        want = min(stations, key=lambda s: _dist_m(lat, lon, s[0], s[1]))
        got = store.nearest_station(lat, lon)
        assert got is not None
        assert got["uic"] == want[2]
        assert set(got) == {"lat", "lon", "uic"}   # _enrich_uic's shape

    far_lat, far_lon = 48.85, 2.35
    assert store.nearest_station(far_lat, far_lon) is None
    assert store.nearest_station(far_lat, far_lon, radius_m=400_000) is not None


def test_relations_near_finds_a_relation_from_its_own_track(store):
    conn = sqlite3.connect(store.path)
    rel_id, geom = conn.execute(
        "SELECT rw.rel_id, w.geom FROM relation_way rw JOIN way w ON w.id = rw.way_id "
        "WHERE w.rail = 1 LIMIT 1").fetchone()
    conn.close()
    pt = decode_geometry(geom)[0]
    assert rel_id in store.relations_near(pt["lat"], pt["lon"], radius_m=1000)
    # Strategy B's intersection: a point 200 km away shares no relation with it.
    assert not store.relations_near(pt["lat"], pt["lon"], 1000) & store.relations_near(
        48.85, 2.35, 1000)


# ---------------------------------------------------------------------------
# Strategy A's lookup, on an extract built to have what it needs
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def synthetic_store(tmp_path_factory):
    """Two stations on one line, both members of one route=train relation.

    Real extracts cannot be relied on for this: in Luxembourg no route relation
    references a node tagged station/halt at all — the members are
    stop_position nodes — so the fixture's relation_uic table is empty and the
    strategy-A lookup would go untested against real data.
    """
    import osmium
    from osmium.osm import mutable

    pbf = tmp_path_factory.mktemp("synth") / "synth-rail.osm.pbf"
    writer = osmium.SimpleWriter(str(pbf))
    writer.add_node(mutable.Node(
        id=1, location=(6.10, 49.60), tags={"railway": "station", "uic_ref": "08200100"}))
    writer.add_node(mutable.Node(
        id=2, location=(6.20, 49.70), tags={"railway": "stop", "uic_ref": "8200200"}))
    writer.add_node(mutable.Node(id=3, location=(6.10, 49.60)))
    writer.add_node(mutable.Node(id=4, location=(6.20, 49.70)))
    writer.add_way(mutable.Way(id=10, nodes=[3, 4], tags={"railway": "rail"}))
    writer.add_way(mutable.Way(id=11, nodes=[3, 4], tags={"railway": "rail", "service": "yard"}))
    writer.add_relation(mutable.Relation(
        id=100,
        members=[("w", 10, ""), ("n", 1, "stop"), ("n", 2, "stop")],
        tags={"route": "train", "name": "Test line"}))
    writer.close()

    out = tmp_path_factory.mktemp("synthstore") / store_filename("europe/synth")
    build_store(pbf, out, region="europe/synth")
    with RailStore(out) as s:
        yield s


def test_relations_for_uic_pair_matches_strategy_a(synthetic_store):
    store = synthetic_store
    assert store.relations_for_uic_pair("8200100", "8200200") == [100]
    # HAFAS and OSM disagree about leading zeros; both sides are normalised.
    assert store.relations_for_uic_pair("008200100", "08200200") == [100]
    assert store.relations_for_uic_pair("8200100", "9999999") == []
    assert store.relations_for_uic_pair("", "8200200") == []

    rel = store.relation_geometry([100])[0]
    assert rel["tags"] == {"route": "train", "name": "Test line"}
    assert [m["ref"] for m in rel["members"]] == [10]


def test_builder_applies_the_strategy_c_way_selection(synthetic_store):
    """A ``service`` way is track, but not track a route may use — the same
    exclusion the Overpass bbox query makes."""
    store = synthetic_store
    assert int(store.meta["ways"]) == 1        # way 10 only
    assert int(store.meta["member_ways"]) == 1  # way 11, kept for its geometry
    assert [w["id"] for w in store.ways_in_bbox(49.5, 6.0, 49.8, 6.3)] == [10]
    # A stop_position node is not a station: it answers strategy A, never _enrich_uic.
    assert int(store.meta["stations"]) == 1
    assert store.nearest_station(49.70, 6.20, radius_m=1000) is None
    assert store.nearest_station(49.60, 6.10, radius_m=1000)["uic"] == "08200100"


# ---------------------------------------------------------------------------
# Resource bounds
# ---------------------------------------------------------------------------

def test_lru_evicts_and_never_holds_a_region_in_memory(tmp_path, store_path):
    """Three regions through a two-slot cache: the oldest is closed, and the
    Python heap never grows by anything like a region's worth of geometry.

    The ceiling is the regression this test exists for — a change that starts
    caching built graphs per region would blow through it, and Germany's graph
    measured 319 MB resident in the spike.
    """
    regions = ["europe/a", "europe/b", "europe/c"]
    for region in regions:
        shutil.copy(store_path, tmp_path / store_filename(region))

    cache = RailStoreCache(tmp_path, max_open=2)
    tracemalloc.start()
    first = cache.get("europe/a")
    before = tracemalloc.get_traced_memory()[0]
    for region in regions:
        s = cache.get(region)
        min_lat, min_lon, max_lat, max_lon = s.bbox
        s.ways_in_bbox(min_lat, min_lon, max_lat, max_lon)
        s.nearest_node((min_lat + max_lat) / 2, (min_lon + max_lon) / 2)
    peak = tracemalloc.get_traced_memory()[1] - before
    tracemalloc.stop()

    assert len(cache._open) == 2
    assert peak < 64 * 1024 * 1024, f"held {peak / 1e6:.1f} MB of Python objects"

    # The evicted region is gone from the cache, and asking for it again opens a
    # new store — but the handle a caller is already holding keeps working, so a
    # resolve in flight when a third region arrives does not fail.
    assert "europe/a" not in cache._open
    assert cache.get("europe/a") is not first
    assert first.nearest_node(49.6, 6.1) is not None

    assert cache.get("europe/nowhere") is None      # not covered, not an error
    cache.close_all()
    assert cache._open == {}


def test_cold_open_and_lookups_are_fast(store_path):
    """Budget check, generously set: this is the per-resolve cost Phase 3 pays.

    The spike's naive graph build cost 8.41 s for Germany and 1.43 s per
    snap before answering anything. Opening a store touches no geometry at all,
    so anything approaching a second here means something is scanning what the
    index should have narrowed.
    """
    t0 = time.monotonic()
    store = RailStore(store_path)
    min_lat, min_lon, max_lat, max_lon = store.bbox
    load = time.monotonic() - t0

    mid_lat, mid_lon = (min_lat + max_lat) / 2, (min_lon + max_lon) / 2
    t0 = time.monotonic()
    for _ in range(10):
        store.nearest_node(mid_lat, mid_lon)
        store.nearest_station(mid_lat, mid_lon, radius_m=50_000)
    lookups = time.monotonic() - t0
    store.close()

    assert load < 1.0, f"cold open took {load:.2f}s"
    assert lookups < 2.0, f"20 point lookups took {lookups:.2f}s"


def test_reader_refuses_a_store_it_does_not_understand(tmp_path, store_path):
    path = tmp_path / store_filename("europe/wrong-schema")
    shutil.copy(store_path, path)
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA user_version = 99")
    conn.close()
    with pytest.raises(RailStoreError):
        RailStore(path)
    with pytest.raises(RailStoreError):
        RailStore(tmp_path / "does-not-exist.rail.sqlite")


def test_store_is_read_only(store):
    with pytest.raises(sqlite3.OperationalError):
        store._conn.execute("DELETE FROM way")
