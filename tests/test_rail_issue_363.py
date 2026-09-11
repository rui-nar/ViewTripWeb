"""The reported leg, on the real relation that got it wrong (#363).

Paris Montparnasse → Bordeaux Saint-Jean resolves onto the right relation and
the right line, and starts 3.5 km late — at the Petite Ceinture, because OSM's
membership does not join the Montparnasse station throat to the main line and
Overpass returns the same gap.

The relation is **5928800**, ``TGV 405 : Paris -- Angoulême -- Bordeaux --
Arcachon``, trimmed out of the published France store. It is one of three
candidates for this UIC pair and all three fail identically: every member way
held (``missing_members = 0``), not one platform member, and the same 322-node
island covering the throat.

What is in the file that closes it is the relation's own stop sequence — node
member 65331500, ``uic_ref`` 8739100, Paris Montparnasse, with coordinates.
:func:`test_the_fixture_still_contains_the_trap` asserts the three facts that
make this a test rather than a decoration, so a refreshed fixture cannot quietly
turn it into a test of nothing.
"""
import json
import os

import pytest

from src.services.overpass_service import (
    _COMPONENT_BRIDGE_M,
    _ENDPOINT_TOLERANCE_KM,
    _best_relation_geometry,
    _bridge_to_named_stops,
    _build_rail_graph,
    _components,
    _crow_km,
    _extract_relation_geometry,
    _is_route_path,
    _polyline_km,
    _relation_stop_near,
)

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "rail", "issue-363-montparnasse.json")

# The stops as `_enrich_uic` leaves them: snapped to the OSM station nodes.
MONTPARNASSE = (48.8400624, 2.3191085)
BORDEAUX = (44.8255227, -0.5556498)

MONTPARNASSE_STOP_NODE = 65331500


@pytest.fixture(scope="module")
def relation():
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)[0]


def _graph(rel):
    return _build_rail_graph([
        m for m in rel["members"]
        if m.get("type") == "way" and len(m.get("geometry", [])) >= 2
        and _is_route_path(m.get("role", ""))])


def _offsets_km(poly):
    return (_crow_km(*MONTPARNASSE, poly[0][1], poly[0][0]),
            _crow_km(*BORDEAUX, poly[-1][1], poly[-1][0]))


# ---------------------------------------------------------------------------
# The fixture really is the failing case
# ---------------------------------------------------------------------------

def test_the_fixture_still_contains_the_trap(relation):
    """Three facts, and the fix rests on all of them.

    Nothing #359 fixed applies — no platform member, no missing member — the
    graph is in pieces with the station throat stranded, and the relation names
    Montparnasse as a located stop. Lose any one and the assertions below would
    pass against a resolver with this fix reverted.
    """
    assert relation["missing_members"] == 0
    assert not [m for m in relation["members"]
                if m.get("type") == "way" and m["role"].startswith("platform")]

    nodes, adj = _graph(relation)
    components = sorted(_components(nodes, adj), key=len, reverse=True)
    assert len(components) > 1, "the graph is no longer in pieces"

    stop = _relation_stop_near(relation, *MONTPARNASSE)
    assert stop is not None, "the relation no longer names Montparnasse"
    assert stop == pytest.approx(MONTPARNASSE, abs=1e-6)

    # The island reaches the station; the main line does not.
    def _nearest_m(component):
        return min(_crow_km(*MONTPARNASSE, nodes[n][1], nodes[n][0])
                   for n in component) * 1000

    main, island = components[0], components[1]
    assert _nearest_m(main) > 3_000, "the main line is no longer 3.5 km short"
    assert _nearest_m(island) < 200, "the throat island no longer reaches the station"


def test_the_gap_between_the_throat_and_the_line_is_the_one_the_issue_measured(
        relation):
    """100 m, in the published France extract. It is the number the limit has to
    clear, and the reason the limit is not 50 m."""
    nodes, adj = _graph(relation)
    components = sorted(_components(nodes, adj), key=len, reverse=True)
    main, island = set(components[0]), components[1]

    gap = min(_crow_km(nodes[a][1], nodes[a][0], nodes[b][1], nodes[b][0])
              for a in island for b in main) * 1000
    assert gap == pytest.approx(100, abs=1)
    assert gap <= _COMPONENT_BRIDGE_M


def test_the_relation_names_montparnasse_as_a_located_stop(relation):
    """The member the store did not emit before #363, in Overpass's own shape.

    Overpass's ``out geom`` returns every node member with ``type``, ``ref``,
    ``role``, ``lat`` and ``lon`` — verified against overpass-api.de on this
    relation, all 16 located — and ``RailStore.relation_geometry`` now emits the
    same, which is why this fixture (cut from the store) carries them.
    """
    stops = [m for m in relation["members"] if m.get("type") == "node"]
    assert len(stops) == 16
    assert all(m.get("lat") is not None and "role" in m for m in stops)

    montparnasse = next(m for m in stops if m["ref"] == MONTPARNASSE_STOP_NODE)
    assert montparnasse["role"] == "stop"
    assert (montparnasse["lat"], montparnasse["lon"]) == pytest.approx(
        MONTPARNASSE, abs=1e-6)


# ---------------------------------------------------------------------------
# …and it now starts at the station
# ---------------------------------------------------------------------------

def test_the_leg_now_starts_at_montparnasse(relation):
    poly = _extract_relation_geometry(relation, *MONTPARNASSE, *BORDEAUX)

    assert poly is not None
    start_km, end_km = _offsets_km(poly)
    assert start_km < 0.15, f"starts {start_km * 1000:.0f} m from Montparnasse"
    assert end_km < 0.1
    # 532 km of real line; the fixture's thinned geometry measures a little short.
    assert 500 < _polyline_km(poly) < 560

    assert _best_relation_geometry([relation], *MONTPARNASSE, *BORDEAUX) is not None


def test_without_the_stop_sequence_it_is_the_3_5_km_short_line_again(relation):
    """The reported symptom, reproduced by taking away only the node members.

    Same ways, same graph, same 100 m gap — the relation simply no longer says
    it calls at Montparnasse, and there is nothing to bridge towards. This is
    what every store on the box returned before #363, since the node members
    were not in ``relation_geometry``'s output at all.
    """
    stripped = dict(relation, members=[m for m in relation["members"]
                                       if m.get("type") != "node"])
    poly = _extract_relation_geometry(stripped, *MONTPARNASSE, *BORDEAUX)

    start_km, _ = _offsets_km(poly)
    assert 3 < start_km < 4, "this is the 3.5 km reported in the issue"
    # And it was never refused: 3.5 km is inside the tolerance, which is why the
    # leg shipped looking almost right instead of falling through to strategy C.
    assert start_km < _ENDPOINT_TOLERANCE_KM
    assert _best_relation_geometry([stripped], *MONTPARNASSE, *BORDEAUX) is not None


def test_the_line_gains_the_throat_and_nothing_else(relation):
    """One bridge edge at this end, and every other metre drawn is mapped track.

    The polyline's longest segment is unchanged by the fix: the 100 m crossing
    is nowhere near the ~1 km straights the LGV is mapped with, so the gap is
    closed without anything that reads as a jump.
    """
    stripped = dict(relation, members=[m for m in relation["members"]
                                       if m.get("type") != "node"])
    before = _extract_relation_geometry(stripped, *MONTPARNASSE, *BORDEAUX)
    after = _extract_relation_geometry(relation, *MONTPARNASSE, *BORDEAUX)

    def _longest_m(poly):
        return max(_crow_km(poly[i][1], poly[i][0], poly[i + 1][1], poly[i + 1][0])
                   for i in range(len(poly) - 1)) * 1000

    assert _longest_m(after) == pytest.approx(_longest_m(before), rel=0.05)
    assert _polyline_km(after) - _polyline_km(before) == pytest.approx(4, abs=2)


def test_only_the_gaps_next_to_a_named_stop_are_bridged(relation):
    """Bounded work, not a repair pass over the relation.

    Both endpoints anchor here — Montparnasse in the throat island, Bordeaux on
    the main line — so the main line also picks up the small gaps it comes
    within 250 m of. What is not touched is any component holding no stop this
    leg names.
    """
    nodes, adj = _graph(relation)
    components = _components(nodes, adj)
    added = _bridge_to_named_stops(relation, nodes, adj, *MONTPARNASSE, *BORDEAUX)

    assert 0 < added < len(components), "a bridge per component pair is too many"
    assert len(_components(nodes, adj)) < len(components), "nothing was joined"
