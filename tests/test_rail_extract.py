"""The rail extract's tag selection and manifest (issue #345, phase 1).

The filter decides what route resolution can see. Widen it and unconnected
sidings enter the graph, which the spike showed *breaks* routes that work
today; narrow it and strategies stop finding things Overpass finds. Neither
failure is visible in any other test — the artifact is built monthly in CI, and
by the time a wrong selection shows up it is a wrong polyline on a user's trip.
The contract itself was wrong once (#349) and nothing caught it, which is what
these assertions exist for.

So the selection is pinned against a checked-in extract with known contents:
two 900 m boxes in Mannheim — one over the ARENA/Maimarkt halt, one over
Neuostheim — cut from Germany's Geofabrik extract with ``osmium extract`` and
joined with ``osmium merge`` (OpenStreetMap data, ODbL). Two boxes rather than
one because the dense kilometre between them costs 600 KB and decides nothing;
this way the fixture is 420 KB and still holds one of everything the filter has
to rule on:

- 12 ``railway=rail`` and 27 ``narrow_gauge`` ways to keep, against 152
  service-tagged ones to drop and 49 trams, 12 platforms and a signal box
  besides;
- 11 nodes carrying ``uic_ref`` that are *not* tagged as stations — tram stops,
  a bus stop, ``public_transport=stop_position`` — which is the row #349
  corrected and the reason strategy A can find a relation at all;
- a station mapped as a way (ARENA/Maimarkt) and one mapped as a relation
  (Neuostheim), neither of which the old node-only contract could see;
- ``route=train`` and ``route=railway`` relations to keep, against trams,
  buses, cycle routes, a pipeline and a waterway to drop.

The expected counts below are therefore not magic numbers: changing the
selection changes them, which is the point. The counts under "the fixture is
worth testing against" are the other half — a widened filter can make an
assertion pass vacuously, and those keep each row of the contract represented.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import osmium
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "rail_mannheim.osm.pbf"

_spec = importlib.util.spec_from_file_location(
    "build_rail_extract", ROOT / "scripts" / "build_rail_extract.py"
)
rail = importlib.util.module_from_spec(_spec)
# Registered before execution because the module defines a dataclass, and
# dataclasses resolve their annotations through sys.modules.
sys.modules[_spec.name] = rail
_spec.loader.exec_module(rail)

# What the fixture holds, counted from the raw box (see the docstring).
EXPECTED_WAYS = 39
EXPECTED_RELATIONS = 59
EXPECTED_STATIONS = 4
EXPECTED_UIC_NODES = 13


@pytest.fixture(scope="module")
def filtered(tmp_path_factory):
    """The fixture box put through the exact selection."""
    out = tmp_path_factory.mktemp("rail") / "mannheim-rail.osm.pbf"
    selection = rail.select(FIXTURE, out)
    return out, selection


@pytest.fixture(scope="module")
def contents(filtered):
    """(nodes, ways, relations) of the filtered file, as plain dicts."""
    path, _ = filtered
    nodes, ways, relations = {}, {}, {}
    for obj in osmium.FileProcessor(str(path)):
        if obj.is_node():
            nodes[obj.id] = (dict(obj.tags), obj.location.lon, obj.location.lat)
        elif obj.is_way():
            ways[obj.id] = (dict(obj.tags), [n.ref for n in obj.nodes])
        else:
            relations[obj.id] = (dict(obj.tags),
                                 [(m.type, m.ref) for m in obj.members])
    return nodes, ways, relations


# ---------------------------------------------------------------------------
# The predicates, stated on their own
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("tags,kept", [
    ({"railway": "rail"}, True),
    ({"railway": "narrow_gauge"}, True),
    ({"railway": "light_rail"}, True),
    # `service` at any value is a siding, a yard track or a spur.
    ({"railway": "rail", "service": "siding"}, False),
    ({"railway": "rail", "service": "yard"}, False),
    ({"railway": "rail", "service": "crossover"}, False),
    ({"railway": "tram"}, False),
    ({"railway": "disused"}, False),
    ({"railway": "platform"}, False),
    ({"highway": "residential"}, False),
])
def test_rail_way_predicate(tags, kept):
    """Mirrors way["railway"~"^(rail|narrow_gauge|light_rail)$"]["service"!~"."]."""
    assert rail.is_rail_way(tags) is kept


@pytest.mark.parametrize("tags,kept", [
    ({"route": "train"}, True),
    # Strategy A lists all three separately; strategy B matches the same three
    # as one regex. Dropping either of these two was the #349 contract error.
    ({"route": "railway"}, True),
    ({"route": "light_rail"}, True),
    ({"route": "bus"}, False),
    ({"route": "ferry"}, False),
    ({"route": "tram"}, False),
    ({"type": "multipolygon"}, False),
])
def test_route_relation_predicate(tags, kept):
    assert rail.is_route_relation(tags) is kept


@pytest.mark.parametrize("tags,kept", [
    # _route_relation_segment matches node["uic_ref"=X] with *no* railway
    # filter, and relations reference the stop node, which is routinely
    # untagged as a station (#349).
    ({"uic_ref": "8000284"}, True),
    ({"railway": "stop", "uic_ref": "8000284"}, True),
    ({"public_transport": "stop_position", "uic_ref": "8000284"}, True),
    ({"railway": "station", "uic_ref": "8000284"}, True),
    ({"railway": "border", "uic_ref": "8000079"}, True),
    ({"railway": "station"}, False),
    ({"uic_ref": ""}, False),
    ({"railway": "rail"}, False),
])
def test_uic_node_predicate(tags, kept):
    assert rail.is_uic_node(tags) is kept


@pytest.mark.parametrize("tags,kept", [
    ({"railway": "station", "uic_ref": "8000284"}, True),
    ({"railway": "halt", "uic_ref": "8000766"}, True),
    # A station with no UIC code cannot answer the lookup it exists for.
    ({"railway": "station"}, False),
    ({"railway": "station", "uic_ref": ""}, False),
    ({"railway": "stop", "uic_ref": "1"}, False),
    ({"public_transport": "station", "uic_ref": "1"}, False),
])
def test_station_predicate(tags, kept):
    """Mirrors node|way|rel ["railway"~"^(station|halt)$"]["uic_ref"]."""
    assert rail.is_station(tags) is kept


# ---------------------------------------------------------------------------
# The fixture is worth testing against
#
# Each row of the contract has to be represented in the fixture, or the
# assertions below it pass for the wrong reason. A filter that is too wide is
# caught by pinned counts; a fixture that is too thin is caught here.
# ---------------------------------------------------------------------------

def test_fixture_holds_uic_nodes_that_are_not_stations(contents):
    """The row #349 corrected: strategy A finds relations through these."""
    nodes, _, _ = contents
    bare = [tags for tags, _, _ in nodes.values()
            if rail.is_uic_node(tags) and not rail.is_station(tags)]
    assert bare, "fixture cannot detect a regression on the node row"


def test_fixture_holds_a_station_mapped_as_a_way(contents):
    """The other row #349 corrected: _find_station_near queries ways too."""
    _, ways, _ = contents
    assert [w for w, (tags, _) in ways.items() if rail.is_station(tags)]


def test_fixture_holds_more_than_one_route_type(contents):
    """route=railway and route=light_rail are as much strategy A's as train."""
    _, _, relations = contents
    assert len({tags["route"] for tags, _ in relations.values()
                if rail.is_route_relation(tags)}) > 1


def test_fixture_holds_service_ways_to_exclude():
    """The one row that excludes rather than includes."""
    excluded = [obj for obj in osmium.FileProcessor(str(FIXTURE), osmium.osm.WAY)
                if obj.tags.get("railway") in rail.RAIL_WAY_TYPES
                and "service" in obj.tags]
    assert excluded


# ---------------------------------------------------------------------------
# The selection, against the fixture
# ---------------------------------------------------------------------------

def test_counts_are_pinned(filtered):
    """A change in what the filter selects has to fail here, loudly."""
    _, selection = filtered
    assert (selection.ways, selection.relations, selection.stations,
            selection.uic_nodes) == (
        EXPECTED_WAYS, EXPECTED_RELATIONS, EXPECTED_STATIONS, EXPECTED_UIC_NODES
    )


def test_counts_describe_the_file_that_was_written(contents, filtered):
    """The manifest's numbers must be of the artifact, not of some earlier pass."""
    nodes, ways, relations = contents
    _, selection = filtered
    assert sum(1 for tags, _ in ways.values() if rail.is_rail_way(tags)) \
        == selection.ways
    assert sum(1 for tags, _ in relations.values() if rail.is_route_relation(tags)) \
        == selection.relations
    assert sum(1 for tags, _, _ in nodes.values() if rail.is_uic_node(tags)) \
        == selection.uic_nodes
    stations = (
        sum(1 for tags, _, _ in nodes.values() if rail.is_station(tags))
        + sum(1 for tags, _ in ways.values() if rail.is_station(tags))
        + sum(1 for tags, _ in relations.values() if rail.is_station(tags))
    )
    assert stations == selection.stations


def test_no_service_way_survives(contents):
    """Sidings beat the through line when _nearest_node snaps (spike finding)."""
    _, ways, _ = contents
    assert not [way for way, (tags, _) in ways.items()
                if tags.get("railway") in rail.RAIL_WAY_TYPES and "service" in tags]


def test_every_way_is_rail_a_station_or_a_station_member(contents):
    """Nothing else has a reason to be in the file."""
    nodes, ways, relations = contents
    station_members = {ref for tags, members in relations.values()
                       if rail.is_station(tags)
                       for kind, ref in members if kind == "w"}
    for way, (tags, _) in ways.items():
        assert rail.is_rail_way(tags) or rail.is_station(tags) \
            or way in station_members


def test_narrow_gauge_is_kept(contents):
    """The way query is a three-value regex, not railway=rail.

    Mannheim's OEG line is narrow_gauge, and a filter that quietly became
    railway=rail would take most of the fixture's kept ways with it.
    """
    _, ways, _ = contents
    assert any(tags.get("railway") == "narrow_gauge" for tags, _ in ways.values())


def test_trams_do_not_survive(contents):
    """The sharpest neighbour: 49 tram ways run through this box and the
    regex excludes every one of them."""
    _, ways, _ = contents
    assert not [tags for tags, _ in ways.values() if tags.get("railway") == "tram"]


def test_only_route_and_station_relations_survive(contents):
    _, _, relations = contents
    for tags, _ in relations.values():
        assert rail.is_route_relation(tags) or rail.is_station(tags)


def test_bus_relations_do_not_survive(contents):
    """The fixture is full of them; a filter keyed on `route` alone would keep
    them and quietly triple the file."""
    _, _, relations = contents
    assert not [tags for tags, _ in relations.values() if tags.get("route") == "bus"]


def test_every_station_carries_a_uic_ref(contents):
    nodes, ways, relations = contents
    tagged = [tags for tags, _, _ in nodes.values()] \
        + [tags for tags, _ in ways.values()] \
        + [tags for tags, _ in relations.values()]
    stations = [tags for tags in tagged
                if tags.get("railway") in rail.STATION_RAILWAY_TYPES]
    assert stations, "the fixture must contain a station to be worth checking"
    assert all(tags.get("uic_ref") for tags in stations)


def test_the_maimarkt_halt_is_among_the_stations(contents):
    """A named element, so a selection that keeps the right *number* by luck fails."""
    nodes, ways, _ = contents
    uic = {tags["uic_ref"] for tags, _, _ in nodes.values() if tags.get("uic_ref")}
    uic |= {tags["uic_ref"] for tags, _ in ways.values() if tags.get("uic_ref")}
    assert "8003841" in uic


def test_kept_ways_keep_all_their_nodes(contents):
    """Geometry is the whole point: a way missing a node cannot be routed on,
    and a station polygon missing one has no centre.

    This is what the multi-pass selection buys — dropping the nodes of the ways
    the prefilter over-selected without dropping the nodes of the ways kept.
    """
    nodes, ways, _ = contents
    for way, (_, refs) in ways.items():
        missing = [ref for ref in refs if ref not in nodes]
        assert not missing, f"way {way} lost {len(missing)} nodes"


def test_station_relations_keep_their_member_ways(contents):
    """`out center` on a relation needs the geometry underneath it."""
    nodes, ways, relations = contents
    for rel, (tags, members) in relations.items():
        if not rail.is_station(tags):
            continue
        for kind, ref in members:
            if kind == "w":
                assert ref in ways, f"station relation {rel} lost way {ref}"
            elif kind == "n":
                assert ref in nodes, f"station relation {rel} lost node {ref}"


def test_untagged_nodes_are_only_there_to_carry_geometry(contents):
    """No node survives that no kept way references and that has no UIC code."""
    nodes, ways, _ = contents
    referenced = {ref for _, refs in ways.values() for ref in refs}
    for node, (tags, _, _) in nodes.items():
        assert node in referenced or rail.is_uic_node(tags)


def test_bbox_is_the_true_extent_not_the_cut_box(filtered, contents):
    """Phase 3 picks a region by this box, so it must not claim empty space."""
    nodes, _, _ = contents
    _, selection = filtered
    lons = [lon for _, lon, _ in nodes.values()]
    lats = [lat for _, _, lat in nodes.values()]
    min_lon, min_lat, max_lon, max_lat = selection.bbox
    assert (min_lon, min_lat) == pytest.approx((min(lons), min(lats)), abs=1e-5)
    assert (max_lon, max_lat) == pytest.approx((max(lons), max(lats)), abs=1e-5)


def test_an_extract_with_no_rail_is_an_error(tmp_path):
    """Publishing an empty region would degrade every route in it to a straight
    line, silently. Better to fail the build."""
    empty = tmp_path / "empty.osm.pbf"
    writer = osmium.SimpleWriter(str(empty))
    writer.close()
    with pytest.raises(RuntimeError, match="no rail data"):
        rail.select(empty, tmp_path / "out.osm.pbf")


def test_metadata_is_dropped(filtered):
    """Version/timestamp/user are ~15 % of the file and nothing reads them."""
    path, _ = filtered
    for obj in osmium.FileProcessor(str(path)):
        assert obj.version == 0
        break


# ---------------------------------------------------------------------------
# The manifest — the phase 1 / phase 2 contract
# ---------------------------------------------------------------------------

CONTRACT_KEYS = {
    "region", "file", "source", "source_date", "sha256", "bytes",
    "ways", "relations", "stations", "bbox",
}


@pytest.fixture(scope="module")
def entry(filtered):
    path, selection = filtered
    return rail.manifest_entry("europe/germany", path, selection, "2026-09-05")


def test_entry_has_exactly_the_contract_keys(entry):
    """Phase 2 reads this. Extra keys are a contract change, not a detail —
    including the uic_nodes count, which stays in the build log."""
    assert set(entry) == CONTRACT_KEYS


def test_entry_describes_the_file_on_disk(entry, filtered):
    path, _ = filtered
    assert entry["file"] == path.name
    assert entry["bytes"] == path.stat().st_size
    assert entry["sha256"] == rail.sha256_file(path)
    assert entry["source"] == \
        "https://download.geofabrik.de/europe/germany-latest.osm.pbf"
    assert entry["source_date"] == "2026-09-05"


def test_source_date_comes_from_the_extract_not_the_clock(tmp_path):
    """The artifact is versioned by the data's date, so a rebuild of unchanged
    data is recognisably the same data."""
    stamped = tmp_path / "stamped.osm.pbf"
    header = osmium.io.Header()
    header.set("osmosis_replication_timestamp", "2026-09-05T21:20:02Z")
    osmium.SimpleWriter(str(stamped), header=header).close()

    assert rail.source_date(stamped) == "2026-09-05"


def test_an_undated_source_is_an_error(tmp_path):
    """A stale extract is the failure that looks like success (plan, phase 5),
    so an extract whose date we cannot read must not build at all.

    The fixture is undated because ``osmium extract`` does not carry the
    replication timestamp through; Geofabrik's own downloads all have one.
    """
    with pytest.raises(RuntimeError, match="replication timestamp"):
        rail.source_date(FIXTURE)


def test_merge_orders_regions_and_stamps_the_schema(entry):
    other = {**entry, "region": "europe/austria"}
    manifest = rail.merge_manifest([entry, other], generated_at="2026-09-06T18:00:00Z")
    assert manifest["schema"] == rail.MANIFEST_SCHEMA == 1
    assert manifest["generated_at"] == "2026-09-06T18:00:00Z"
    assert [r["region"] for r in manifest["regions"]] == [
        "europe/austria", "europe/germany"
    ]


def test_generated_at_is_utc_and_iso():
    manifest = rail.merge_manifest([])
    assert manifest["generated_at"].endswith("Z")
    assert len(manifest["generated_at"]) == 20


def test_verify_accepts_an_untouched_build(entry, filtered):
    path, _ = filtered
    rail.verify_manifest(rail.merge_manifest([entry]), path.parent)


def test_verify_rejects_a_truncated_file(entry, tmp_path):
    """The artifact crosses a job boundary between build and publish."""
    (tmp_path / entry["file"]).write_bytes(b"not a pbf")
    with pytest.raises(ValueError, match="bytes"):
        rail.verify_manifest(rail.merge_manifest([entry]), tmp_path)


def test_verify_rejects_a_corrupted_file(entry, tmp_path):
    (tmp_path / entry["file"]).write_bytes(b"\0" * entry["bytes"])
    with pytest.raises(ValueError, match="checksum"):
        rail.verify_manifest(rail.merge_manifest([entry]), tmp_path)


def test_verify_rejects_a_missing_file(entry, tmp_path):
    with pytest.raises(ValueError, match="missing"):
        rail.verify_manifest(rail.merge_manifest([entry]), tmp_path)


def test_verify_rejects_an_unknown_schema(entry, filtered):
    path, _ = filtered
    manifest = {**rail.merge_manifest([entry]), "schema": 2}
    with pytest.raises(ValueError, match="schema"):
        rail.verify_manifest(manifest, path.parent)


def test_collect_writes_and_verifies_the_published_manifest(filtered, entry, tmp_path):
    """What the publish job runs: entry files in, verified manifest.json out."""
    path, _ = filtered
    (tmp_path / path.name).write_bytes(path.read_bytes())
    (tmp_path / f"germany{rail.ENTRY_SUFFIX}").write_text(json.dumps(entry))

    manifest = rail.collect_manifest(tmp_path)

    written = json.loads((tmp_path / rail.MANIFEST_NAME).read_text())
    assert written == manifest
    assert [r["region"] for r in written["regions"]] == ["europe/germany"]


def test_collect_refuses_to_publish_nothing(tmp_path):
    """An empty directory would otherwise publish an empty manifest, which
    phase 3 reads as "Europe is not covered"."""
    with pytest.raises(RuntimeError, match="no .* files"):
        rail.collect_manifest(tmp_path)
