"""Store schema 2: member roles, ordered stop nodes, and reading a schema 1 file (#359).

Schema 2 adds two things and drops none:

* ``relation_way.role`` — without it the resolver cannot tell a route's path
  from a platform it merely touches, which is issue #359;
* ``relation_node`` — every node member in member order, which is what a
  relation calls at and in what sequence. Nothing reads it yet, deliberately;
  it is here because adding it later costs a rebuild of all 49 regions and
  adding it during this bump costs nothing.

The third thing under test is the *absence* of a cutover: a reader that accepts
only its own schema turns every bump into an Overpass outage, whichever order
code and data ship in.
"""
import shutil
import sqlite3

import pytest
from osmium.osm import mutable
import osmium

from src.rail.builder import build_store
from src.rail.store import (
    SCHEMA_VERSION,
    _SUPPORTED_SCHEMAS,
    RailStore,
    RailStoreError,
    store_filename,
)
from src.services.overpass_service import _extract_relation_geometry

REGION = "europe/roles"


def _write_extract(path):
    """Track, a platform beside it, and a route relation naming both.

    The relation's members are ordered so that the reader has something to get
    wrong: a platform first, then track, and node members whose sequence is not
    their id order.
    """
    w = osmium.SimpleWriter(str(path))
    # Two stop nodes carrying uic_ref (Phase 1 keeps these, so they are located)
    # and one that carries none (named in sequence, never located).
    w.add_node(mutable.Node(id=1, location=(6.10, 49.60),
                            tags={"railway": "station", "uic_ref": "8200100"}))
    w.add_node(mutable.Node(id=2, location=(6.20, 49.70),
                            tags={"railway": "station", "uic_ref": "8200200"}))
    w.add_node(mutable.Node(id=3, location=(6.15, 49.65)))
    # Track, in two ways sharing node 5.
    for nid, (lon, lat) in enumerate(
            [(6.10, 49.60), (6.15, 49.65), (6.20, 49.70)], start=4):
        w.add_node(mutable.Node(id=nid, location=(lon, lat)))
    # A platform ring beside the first station, touching no track.
    for nid, (lon, lat) in enumerate(
            [(6.1002, 49.6002), (6.1004, 49.6002), (6.1004, 49.6004)], start=7):
        w.add_node(mutable.Node(id=nid, location=(lon, lat)))

    w.add_way(mutable.Way(id=10, nodes=[4, 5], tags={"railway": "rail"}))
    w.add_way(mutable.Way(id=11, nodes=[5, 6], tags={"railway": "rail"}))
    w.add_way(mutable.Way(id=12, nodes=[7, 8, 9, 7], tags={"railway": "platform"}))
    # A way the route runs on that a mapper labelled, which is not a platform.
    w.add_way(mutable.Way(id=13, nodes=[4, 5], tags={"railway": "rail"}))

    w.add_relation(mutable.Relation(
        id=100,
        members=[("w", 12, "platform"), ("w", 10, ""), ("w", 13, "forward"),
                 ("w", 11, ""),
                 ("n", 2, "stop"), ("n", 3, "stop"), ("n", 1, "stop_exit_only")],
        tags={"route": "train", "name": "Roles line"}))
    w.close()


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    pbf = tmp_path_factory.mktemp("roles") / "roles-rail.osm.pbf"
    _write_extract(pbf)
    out = tmp_path_factory.mktemp("rolestore") / store_filename(REGION)
    build_store(pbf, out, region=REGION)
    with RailStore(out) as s:
        yield s


# ---------------------------------------------------------------------------
# relation_way.role
# ---------------------------------------------------------------------------

def test_the_store_is_written_at_the_current_schema(store):
    conn = sqlite3.connect(store.path)
    assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    conn.close()
    assert store.schema == SCHEMA_VERSION


def test_member_roles_survive_the_round_trip_verbatim(store):
    rel = store.relation_geometry([100])[0]
    assert [(m["ref"], m["role"]) for m in rel["members"]] == [
        (12, "platform"), (10, ""), (13, "forward"), (11, ""),
    ], "member order and role must both be preserved"


def test_the_resolver_routes_past_the_platform_on_real_store_output(store):
    """End to end through the store: the shape #359 failed on.

    The platform ring sits 25 m from the first station and the track's nearest
    vertex is on the station itself, so this only distinguishes the fix if the
    ring is genuinely excluded — hence the explicit check that no ring vertex
    is on the line.
    """
    rel = store.relation_geometry([100])[0]
    poly = _extract_relation_geometry(rel, 49.60, 6.10, 49.70, 6.20)

    assert poly is not None
    ring = {(6.1002, 49.6002), (6.1004, 49.6002), (6.1004, 49.6004)}
    assert not ring & {tuple(pt) for pt in poly}
    assert poly[0] == [6.10, 49.60] and poly[-1] == [6.20, 49.70]


# ---------------------------------------------------------------------------
# relation_node — the ordered stop sequence
# ---------------------------------------------------------------------------

def test_stop_nodes_are_kept_in_member_order_not_id_order(store):
    stops = store.relation_stops(100)
    assert [s["ref"] for s in stops] == [2, 3, 1]
    assert [s["role"] for s in stops] == ["stop", "stop", "stop_exit_only"]


def test_a_stop_the_extract_cannot_place_is_named_not_dropped(store):
    """The sequence is the point, and a hole in it is not a shorter route.

    Phase 1 keeps nodes carrying a ``uic_ref``, so an ordinary stop node comes
    through with no location — recorded, and visibly unlocated.
    """
    stops = {s["ref"]: s for s in store.relation_stops(100)}
    assert stops[2]["uic"] == "8200200"
    assert stops[2]["lat"] == pytest.approx(49.70)
    assert stops[3]["uic"] == "" and stops[3]["lat"] is None and stops[3]["lon"] is None
    assert int(store.meta["relation_nodes"]) == 3
    assert int(store.meta["relation_nodes_located"]) == 2


def test_relation_uic_is_unchanged_by_the_new_table(store):
    """Strategy A's pair query is indexed on `relation_uic`, and it still is —
    `relation_node` answers a different question and replaces nothing."""
    assert store.relations_for_uic_pair("8200100", "8200200") == [100]
    assert store.relation_stops(-1) == []


# ---------------------------------------------------------------------------
# Reading a schema 1 file
# ---------------------------------------------------------------------------

def _downgrade_to_schema_1(src, dst):
    """The same store as it was written before #359: no role, no relation_node."""
    shutil.copy(src, dst)
    conn = sqlite3.connect(dst)
    conn.executescript("""
        CREATE TABLE relation_way_v1 (
            rel_id INTEGER NOT NULL,
            way_id INTEGER NOT NULL,
            seq    INTEGER NOT NULL
        );
        INSERT INTO relation_way_v1 SELECT rel_id, way_id, seq FROM relation_way;
        DROP TABLE relation_way;
        ALTER TABLE relation_way_v1 RENAME TO relation_way;
        DROP TABLE relation_node;
        PRAGMA user_version = 1;
    """)
    conn.commit()
    conn.close()
    return dst


def test_a_schema_1_store_still_opens_and_answers(store, tmp_path):
    """The bump must not be a cutover.

    ``_stores_for`` reads a refused store as "region not covered", so a reader
    accepting only its own version refuses every file on the box until the data
    is rebuilt — and shipping the data first would be refused by the old reader
    just as flatly. Either order sends every train resolve to Overpass, on the
    address Overpass has already blocked once. Accepting both is what lets the
    code ship first and the data land whenever it lands.
    """
    old = _downgrade_to_schema_1(store.path, str(tmp_path / store_filename(REGION)))

    with RailStore(old) as legacy:
        assert legacy.schema == 1
        rel = legacy.relation_geometry([100])[0]
        # Every member reads back as path, which is the pre-#359 behaviour
        # exactly — not "unknown, therefore dropped", which would empty it.
        assert [m["ref"] for m in rel["members"]] == [12, 10, 13, 11]
        assert {m["role"] for m in rel["members"]} == {""}
        assert legacy.relation_stops(100) == []
        # The lookups that do not depend on the new columns are untouched.
        assert legacy.relations_for_uic_pair("8200100", "8200200") == [100]
        assert legacy.ways_in_bbox(49.5, 6.0, 50.0, 6.3)


def test_an_unknown_schema_is_still_refused(store, tmp_path):
    """Tolerance is an explicit list, not `>=`: a version with no branch here
    would be read with queries naming columns it may not have, and answering a
    query wrongly is the failure that looks exactly like success."""
    future = str(tmp_path / store_filename("europe/future"))
    shutil.copy(store.path, future)
    conn = sqlite3.connect(future)
    conn.execute(f"PRAGMA user_version = {max(_SUPPORTED_SCHEMAS) + 1}")
    conn.commit()
    conn.close()

    with pytest.raises(RailStoreError, match="schema version"):
        RailStore(future)


def test_the_supported_set_names_the_current_schema():
    assert SCHEMA_VERSION in _SUPPORTED_SCHEMAS
    assert 1 in _SUPPORTED_SCHEMAS, "schema 1 is what is on the box before the refresh"
