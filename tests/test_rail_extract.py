"""The rail extract's tag selection and manifest (issue #345, phase 1).

The filter decides what route resolution can see. Widen it and unconnected
sidings enter the graph, which the spike showed *breaks* routes that work
today; narrow it and lines silently disappear from the map. Neither failure is
visible in any other test — the artifact is built monthly in CI, and by the
time a wrong selection shows up it is a wrong polyline on a user's trip.

So the selection is pinned against a checked-in extract with known contents: a
1.4 x 1.4 km box around Aarhus H, cut from Denmark's Geofabrik extract with
``osmium extract -b 10.198,56.145,10.212,56.158`` (OpenStreetMap data,
ODbL). It is small, and it contains one of everything the filter has to decide
about — 54 rail ways and 41 service-tagged ones, one station with a UIC code
and one without, eight ``route=train`` relations against 78 relations that are
buses, cycle routes, ``route=railway`` and ``route=light_rail``, plus
platform/disused/razed railway ways.

The expected counts below are therefore not magic numbers: changing the
selection changes them, which is the point.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import osmium
import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "rail_aarhus.osm.pbf"

_spec = importlib.util.spec_from_file_location(
    "build_rail_extract", ROOT / "scripts" / "build_rail_extract.py"
)
rail = importlib.util.module_from_spec(_spec)
# Registered before execution because the module defines a dataclass, and
# dataclasses resolve their annotations through sys.modules.
sys.modules[_spec.name] = rail
_spec.loader.exec_module(rail)

# What the fixture holds, counted by hand from the raw box (see the docstring).
EXPECTED_WAYS = 54
EXPECTED_RELATIONS = 8
EXPECTED_STATIONS = 1


@pytest.fixture(scope="module")
def filtered(tmp_path_factory):
    """The fixture box put through the exact selection."""
    out = tmp_path_factory.mktemp("rail") / "aarhus-rail.osm.pbf"
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
            relations[obj.id] = dict(obj.tags)
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
    ({"route": "railway"}, False),
    ({"route": "light_rail"}, False),
    ({"route": "bus"}, False),
    ({"type": "multipolygon"}, False),
])
def test_train_relation_predicate(tags, kept):
    assert rail.is_train_relation(tags) is kept


@pytest.mark.parametrize("tags,kept", [
    ({"railway": "station", "uic_ref": "8600087"}, True),
    ({"railway": "halt", "uic_ref": "8600766"}, True),
    # No UIC code means _enrich_uic cannot use it, so it is dead weight.
    ({"railway": "station"}, False),
    ({"railway": "station", "uic_ref": ""}, False),
    ({"railway": "stop", "uic_ref": "1"}, False),
    ({"public_transport": "station", "uic_ref": "1"}, False),
])
def test_uic_station_predicate(tags, kept):
    assert rail.is_uic_station(tags) is kept


# ---------------------------------------------------------------------------
# The selection, against the fixture
# ---------------------------------------------------------------------------

def test_counts_are_pinned(filtered):
    """A change in what the filter selects has to fail here, loudly."""
    _, selection = filtered
    assert (selection.ways, selection.relations, selection.stations) == (
        EXPECTED_WAYS, EXPECTED_RELATIONS, EXPECTED_STATIONS
    )


def test_counts_describe_the_file_that_was_written(contents, filtered):
    """The manifest's numbers must be of the artifact, not of some earlier pass."""
    nodes, ways, relations = contents
    _, selection = filtered
    assert len(ways) == selection.ways
    assert len(relations) == selection.relations
    assert sum(1 for tags, _, _ in nodes.values() if rail.is_uic_station(tags)) \
        == selection.stations


def test_no_service_way_survives(contents):
    """Sidings beat the through line when _nearest_node snaps (spike finding)."""
    _, ways, _ = contents
    assert not [way for way, (tags, _) in ways.items() if "service" in tags]


def test_only_the_three_railway_types_survive(contents):
    _, ways, _ = contents
    assert {tags["railway"] for tags, _ in ways.values()} <= rail.RAIL_WAY_TYPES


def test_light_rail_is_kept(contents):
    """Aarhus' letbane is light_rail, and the Overpass query includes it."""
    _, ways, _ = contents
    assert any(tags["railway"] == "light_rail" for tags, _ in ways.values())


def test_only_train_relations_survive(contents):
    """route=railway and route=light_rail are in the fixture and must be gone."""
    _, _, relations = contents
    assert {tags.get("route") for tags in relations.values()} == {"train"}


def test_every_station_node_carries_a_uic_ref(contents):
    nodes, _, _ = contents
    stations = [tags for tags, _, _ in nodes.values()
                if tags.get("railway") in rail.STATION_RAILWAY_TYPES]
    assert stations, "the fixture must contain a station to be worth checking"
    assert all(tags.get("uic_ref") for tags in stations)


def test_aarhus_h_is_the_station_that_survives(contents):
    """A named element, so a selection that keeps the right *number* by luck fails."""
    nodes, _, _ = contents
    uic = {tags["uic_ref"] for tags, _, _ in nodes.values() if tags.get("uic_ref")}
    assert uic == {"8600087"}


def test_kept_ways_keep_all_their_nodes(contents):
    """Geometry is the whole point: a way missing a node cannot be routed on.

    This is what the two-pass selection buys — dropping the nodes of the ways
    the prefilter over-selected without dropping the nodes of the ways kept.
    """
    nodes, ways, _ = contents
    for way, (_, refs) in ways.items():
        missing = [ref for ref in refs if ref not in nodes]
        assert not missing, f"way {way} lost {len(missing)} nodes"


def test_untagged_nodes_are_only_there_to_carry_geometry(contents):
    """No node survives that no kept way references and that is not a station."""
    nodes, ways, _ = contents
    referenced = {ref for _, refs in ways.values() for ref in refs}
    for node, (tags, _, _) in nodes.items():
        assert node in referenced or rail.is_uic_station(tags)


def test_bbox_is_the_true_extent_not_the_cut_box(filtered, contents):
    """Phase 3 picks a region by this box, so it must not claim empty space.

    The fixture was cut at 10.198,56.145 - 10.212,56.158; the rail inside it
    reaches neither corner, and the extent reported has to be the data's.
    """
    nodes, _, _ = contents
    _, selection = filtered
    lons = [lon for _, lon, _ in nodes.values()]
    lats = [lat for _, _, lat in nodes.values()]
    min_lon, min_lat, max_lon, max_lat = selection.bbox
    assert (min_lon, min_lat) == pytest.approx((min(lons), min(lats)), abs=1e-5)
    assert (max_lon, max_lat) == pytest.approx((max(lons), max(lats)), abs=1e-5)
    # Strictly inside the cut box on at least one side — a nominal box would
    # have been the cut box itself.
    assert max_lat < 56.158


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
    return rail.manifest_entry("europe/denmark", path, selection, "2026-09-05")


def test_entry_has_exactly_the_contract_keys(entry):
    """Phase 2 reads this. Extra keys are a contract change, not a detail."""
    assert set(entry) == CONTRACT_KEYS


def test_entry_describes_the_file_on_disk(entry, filtered):
    path, _ = filtered
    assert entry["file"] == path.name
    assert entry["bytes"] == path.stat().st_size
    assert entry["sha256"] == rail.sha256_file(path)
    assert entry["source"] == \
        "https://download.geofabrik.de/europe/denmark-latest.osm.pbf"
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
        "europe/austria", "europe/denmark"
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
    (tmp_path / f"denmark{rail.ENTRY_SUFFIX}").write_text(json.dumps(entry))

    manifest = rail.collect_manifest(tmp_path)

    written = json.loads((tmp_path / rail.MANIFEST_NAME).read_text())
    assert written == manifest
    assert [r["region"] for r in written["regions"]] == ["europe/denmark"]


def test_collect_refuses_to_publish_nothing(tmp_path):
    """An empty directory would otherwise publish an empty manifest, which
    phase 3 reads as "Europe is not covered"."""
    with pytest.raises(RuntimeError, match="no .* files"):
        rail.collect_manifest(tmp_path)
