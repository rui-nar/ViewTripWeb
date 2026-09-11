"""Reaching a stop the relation names, across a gap OSM left (#363).

Paris Montparnasse → Bordeaux resolves onto the right relation and the right
line and starts 3.5 km late, at the Petite Ceinture. Nothing #359 fixed applies:
all three candidate relations hold every member way (``missing_members = 0``)
and none has a platform member. Their graphs are simply in pieces, because OSM's
membership does not join the Montparnasse station throat to the main line, and
Overpass returns the same gap.

What closes it is the relation's own stop sequence. It *names* Paris
Montparnasse as a node member with coordinates, a 322-node component reaches
within 13 m of that stop, and that component stops 100 m short of the main line.
So the component holding a named stop may be joined to what it nearly touches,
under a hard metre limit — and nothing else may.

The shapes here are synthetic so the gap is a dial; ``tests/test_rail_issue_363.py``
runs the same assertions against the real relation.
"""
import pytest

from src.services.overpass_service import (
    _COMPONENT_BRIDGE_M,
    _ENDPOINT_TOLERANCE_KM,
    _STOP_ANCHOR_KM,
    _best_relation_geometry,
    _bridge_to_named_stops,
    _build_rail_graph,
    _crow_km,
    _extract_relation_geometry,
    _relation_stop_near,
)

# The reported leg. MONTPARNASSE is the OSM station node `_enrich_uic` snaps to,
# and CEINTURE is where the relation's main line really starts — 3.5 km south,
# which is where the line was being drawn from.
MONTPARNASSE = (48.8401, 2.3191)
BORDEAUX = (44.8258, -0.5561)
CEINTURE = (48.8086, 2.3000)

_M_PER_DEG_LAT = 111_000.0


def _geom(*points):
    return [{"lat": lat, "lon": lon} for lat, lon in points]


def _way(ref, points, role=""):
    return {"type": "way", "ref": ref, "role": role, "geometry": _geom(*points)}


def _stop(point, ref=65331500, role="stop"):
    """A node member as both sources return one: type, ref, role, lat, lon."""
    return {"type": "node", "ref": ref, "role": role,
            "lat": point[0], "lon": point[1]}


# The main line, in two ways sharing a vertex. It starts at the Ceinture and
# reaches Bordeaux; the station throat is not part of it.
MAIN = [
    _way(1, [CEINTURE, (47.4000, 0.7000)]),
    _way(2, [(47.4000, 0.7000), BORDEAUX]),
]


def _throat(gap_m, at=CEINTURE, station=MONTPARNASSE, ref=8):
    """A stub from *station* stopping *gap_m* short of *at*, touching nothing.

    Purely a latitude offset, so the gap is exactly *gap_m* metres by the same
    equirectangular maths ``_bridge_to_named_stops`` measures it with.
    """
    return _way(ref, [station, (at[0] + gap_m / _M_PER_DEG_LAT, at[1])])


def _relation(members, rel_id=5928800):
    return {"type": "relation", "id": rel_id,
            "tags": {"route": "train", "name": "TGV 405 : Paris -- Bordeaux"},
            "members": members, "missing_members": 0}


def _start_km(poly):
    return _crow_km(MONTPARNASSE[0], MONTPARNASSE[1], poly[0][1], poly[0][0])


def _end_km(poly):
    return _crow_km(BORDEAUX[0], BORDEAUX[1], poly[-1][1], poly[-1][0])


def _resolve(members):
    return _extract_relation_geometry(
        _relation(members), *MONTPARNASSE, *BORDEAUX)


# ---------------------------------------------------------------------------
# 1 — the gap closes, and only because the relation names the stop
# ---------------------------------------------------------------------------

def test_a_named_stop_lets_the_leg_reach_a_throat_osm_leaves_disconnected():
    poly = _resolve([_throat(100), *MAIN, _stop(MONTPARNASSE)])

    assert poly is not None
    assert _start_km(poly) < 0.05, f"still starts {_start_km(poly):.1f} km short"
    assert _end_km(poly) < 0.05, "the far end was always right"


def test_the_same_relation_without_the_stop_still_starts_at_the_ceinture():
    """The anchor is what authorises the bridge, not the size of the gap.

    Drop the node member and the geometry is identical — same throat, same
    100 m — and the leg is drawn from the Ceinture again. That is the whole
    difference between this and joining any two components that happen to be
    close, which is what would let a relation serving other stations stitch
    itself into reach of ``_ENDPOINT_TOLERANCE_KM``.
    """
    poly = _resolve([_throat(100), *MAIN])

    assert _start_km(poly) > 3, "something bridged without a stop to bridge to"
    assert _start_km(poly) < _ENDPOINT_TOLERANCE_KM, "this is issue #363's answer"


# ---------------------------------------------------------------------------
# 2 — the metre limit, from both sides
# ---------------------------------------------------------------------------

def test_a_gap_wider_than_the_limit_is_refused():
    """A named stop is permission to cross a mapping gap, not a route to invent."""
    poly = _resolve([_throat(_COMPONENT_BRIDGE_M + 50), *MAIN, _stop(MONTPARNASSE)])

    assert _start_km(poly) > 3, "the bridge is not bounded in metres"


def test_the_limit_is_metres_and_this_is_the_number():
    """Pins the constant and both sides of it.

    A test that only checked "a wide gap is refused" would pass on a limit of
    10 km as well as on 250 m, and 10 km is the Hanko→Salo teleport in a smaller
    hat. The reported gap is 100 m; the limit has to clear that and refuse the
    kilometre tail of the same measurement.
    """
    assert _COMPONENT_BRIDGE_M == 250.0

    inside = _resolve([_throat(200), *MAIN, _stop(MONTPARNASSE)])
    outside = _resolve([_throat(300), *MAIN, _stop(MONTPARNASSE)])

    assert _start_km(inside) < 0.05
    assert _start_km(outside) > 3


def test_the_bridge_is_the_only_segment_that_is_not_track():
    """What is drawn across the gap is one segment, no longer than the limit."""
    throat = _throat(100)
    poly = _resolve([throat, *MAIN, _stop(MONTPARNASSE)])

    crossing = [
        _crow_km(poly[i][1], poly[i][0], poly[i + 1][1], poly[i + 1][0]) * 1000
        for i in range(len(poly) - 1)
        if {tuple(poly[i]), tuple(poly[i + 1])}
        == {(throat["geometry"][1]["lon"], throat["geometry"][1]["lat"]),
            (CEINTURE[1], CEINTURE[0])}
    ]
    assert len(crossing) == 1, "the throat is not joined to the line by one edge"
    assert crossing[0] == pytest.approx(100, abs=1)
    assert crossing[0] <= _COMPONENT_BRIDGE_M


# ---------------------------------------------------------------------------
# 3 — which stop counts
# ---------------------------------------------------------------------------

def test_a_stop_the_relation_names_somewhere_else_does_not_anchor_this_leg():
    """A relation calls at many stations; only the one at this endpoint anchors.

    Otherwise a long-distance relation's stop list would authorise a bridge
    anywhere along it, which is the general gap-chaining this must not become.
    """
    elsewhere = (MONTPARNASSE[0] - 0.05, MONTPARNASSE[1])     # ~5.5 km away
    poly = _resolve([_throat(100), *MAIN, _stop(elsewhere)])

    assert _start_km(poly) > 3


def test_a_stop_the_extract_could_not_place_is_ignored():
    """Phase 1 keeps nodes carrying a ``uic_ref``, so an ordinary stop node comes
    back named and unlocated — ``held: False`` and no coordinates. It says
    nothing about where the relation calls, so it anchors nothing."""
    unplaced = {"type": "node", "ref": 65331500, "role": "stop", "held": False}
    poly = _resolve([_throat(100), *MAIN, unplaced])

    assert _start_km(poly) > 3


@pytest.mark.parametrize("role", ["stop", "stop_entry_only", "stop_exit_only",
                                  "platform", ""])
def test_every_node_member_role_can_anchor(role):
    """``_is_route_path``'s deny-list is about which *ways* carry the train. A
    node member is a point the relation calls at whatever it is labelled, and it
    is only ever read for its coordinates — never put in the graph."""
    poly = _resolve([_throat(100), *MAIN, _stop(MONTPARNASSE, role=role)])
    assert _start_km(poly) < 0.05


def test_relation_stop_near_picks_the_closest_within_the_anchor_radius():
    rel = _relation([_stop((48.8500, 2.3191), ref=1),
                     _stop(MONTPARNASSE, ref=2),
                     _stop(BORDEAUX, ref=3)])

    assert _relation_stop_near(rel, *MONTPARNASSE) == MONTPARNASSE
    assert _relation_stop_near(rel, *BORDEAUX) == BORDEAUX
    # Halfway to nowhere: nothing this relation names is within the radius.
    assert _relation_stop_near(rel, 46.5, 1.0) is None
    assert _STOP_ANCHOR_KM < _ENDPOINT_TOLERANCE_KM, (
        "an anchor must never be why a relation clears the endpoint check")


# ---------------------------------------------------------------------------
# 4 — both ends, and nothing else
# ---------------------------------------------------------------------------

def test_the_far_end_of_the_leg_is_treated_the_same_way():
    """A terminus throat is disconnected as readily at the arrival station."""
    members = [_way(1, [MONTPARNASSE, (47.4000, 0.7000)]),
               _way(2, [(47.4000, 0.7000), (44.8600, -0.5561)]),
               _throat(100, at=(44.8600, -0.5561), station=BORDEAUX, ref=9),
               _stop(MONTPARNASSE, ref=1), _stop(BORDEAUX, ref=2)]
    poly = _extract_relation_geometry(_relation(members), *MONTPARNASSE, *BORDEAUX)

    assert _start_km(poly) < 0.05
    assert _end_km(poly) < 0.05


def test_a_relation_that_names_neither_stop_is_never_touched():
    rel = _relation([_throat(100), *MAIN])
    nodes, adj = _build_rail_graph(rel["members"])
    before = {node: list(neighbours) for node, neighbours in adj.items()}

    assert _bridge_to_named_stops(rel, nodes, adj, *MONTPARNASSE, *BORDEAUX) == 0
    assert adj == before


def test_a_relation_already_in_one_piece_is_never_touched():
    rel = _relation([_way(1, [MONTPARNASSE, BORDEAUX]), _stop(MONTPARNASSE)])
    nodes, adj = _build_rail_graph(rel["members"])
    before = {node: list(neighbours) for node, neighbours in adj.items()}

    assert _bridge_to_named_stops(rel, nodes, adj, *MONTPARNASSE, *BORDEAUX) == 0
    assert adj == before


def test_the_endpoint_tolerance_still_refuses_a_relation_serving_other_stations():
    """The bridge must not become a way past the check that says "this leg".

    This relation is disconnected at its own origin exactly as the reported one
    is, and it names the station it calls at — but that station is 14 km from
    where the traveller boarded, so the bridge it earns only ever reaches its
    own throat, and ``_best_relation_geometry`` refuses it just as before
    (issue #359's `TGV InOui 061C`, whose Paris end is on the Grande Ceinture).
    """
    other_station = (MONTPARNASSE[0] - 0.125, MONTPARNASSE[1])   # ~13.9 km south
    other_throat_end = (other_station[0] - 0.010, other_station[1])
    rel = _relation([_way(21, [other_station, other_throat_end]),
                     _way(22, [(other_throat_end[0] - 100 / _M_PER_DEG_LAT,
                                other_throat_end[1]), (47.4000, 0.7000)]),
                     _way(23, [(47.4000, 0.7000), BORDEAUX]),
                     _stop(other_station), _stop(BORDEAUX, ref=2)],
                    rel_id=5935098)

    # It does route, throat included — that is the trap, not an accident.
    poly = _extract_relation_geometry(_relation(rel["members"]),
                                      *other_station, *BORDEAUX)
    assert _crow_km(*other_station, poly[0][1], poly[0][0]) < 0.05

    assert _best_relation_geometry([rel], *MONTPARNASSE, *BORDEAUX) is None


# ---------------------------------------------------------------------------
# 6 — what the named-stop rule actually restricts  (adversarial review of #375)
# ---------------------------------------------------------------------------

def test_the_main_line_is_never_a_home_however_it_is_named():
    """The restriction that makes the rest of them mean anything.

    A home bridges to *every* component it approaches. The far endpoint's stop
    normally sits on the main line — that end is usually the one that is not
    broken — so anchoring there would make the main line a home and join it to
    every stray fragment within the limit along its whole length. That is the
    general gap-chaining the named-stop rule exists to prevent, arriving
    through the door marked "named stop".

    Here the relation names only Bordeaux, which is on the main line, and a
    stray fragment sits 50 m off the main line far from either endpoint. It
    must not be joined.
    """
    stray = _way(7, [(47.4000, 0.7000 + 0.0007), (47.4100, 0.7007)])
    rel = _relation([*MAIN, stray, _stop(BORDEAUX, ref=2)])
    nodes, adj = _build_rail_graph(rel["members"])
    before = {node: list(neighbours) for node, neighbours in adj.items()}

    assert _bridge_to_named_stops(rel, nodes, adj, *MONTPARNASSE, *BORDEAUX) == 0
    assert adj == before


def test_naming_the_far_stop_does_not_rescue_a_leg_whose_own_throat_is_unnamed():
    """The negative of the headline case, and the one the old code got wrong.

    Same geometry as the fix's headline test, except the relation names only
    the *far* stop. Before the main-line guard this still bridged the throat —
    the main line was a home and reached it — so the relation appeared to be
    rescued by a stop sequence that never mentions Montparnasse.
    """
    members = [_throat(100), *MAIN, _stop(BORDEAUX, ref=2)]
    poly = _resolve(members)

    assert _start_km(poly) > 3.0, "bridged without naming the stop at this end"


def test_the_anchor_radius_is_the_number_it_says():
    """Pins ``_STOP_ANCHOR_KM``, which no other test constrains.

    Widening it silently — 1 km to 5 km — changes which stop anchors a leg and
    so which component may bridge, and every other test in this file passes
    either way. Check both sides of the stated boundary.
    """
    from src.services.overpass_service import _STOP_ANCHOR_KM

    assert _STOP_ANCHOR_KM == 1.0

    def _named_at(km_north):
        stop = (MONTPARNASSE[0] + km_north / 111.0, MONTPARNASSE[1])
        return _resolve([_throat(100), *MAIN, _stop(stop, ref=3)])

    assert _start_km(_named_at(0.5)) < 0.05, "a stop well inside the radius"
    assert _start_km(_named_at(2.0)) > 3.0, "a stop outside it must not anchor"


def test_an_invented_path_is_bounded_at_two_edges_not_one():
    """The bound the docstring now states, rather than the one it used to.

    Two broken throats either side of a shared fragment each bridge to it, so a
    path can cross two invented edges. Both are still ``_COMPONENT_BRIDGE_M``
    or less, which is what keeps this three orders of magnitude away from the
    116 km Hanko-Salo teleport — but "one edge" was wrong.
    """
    mid = (47.4000, 0.7000)
    stepping = _way(6, [(mid[0] + 200 / _M_PER_DEG_LAT, mid[1]),
                        (mid[0] + 201 / _M_PER_DEG_LAT, mid[1])])
    members = [
        _way(1, [MONTPARNASSE, (mid[0] + 400 / _M_PER_DEG_LAT, mid[1])]),
        stepping,
        _way(2, [mid, BORDEAUX]),
        _stop(MONTPARNASSE, ref=1), _stop(BORDEAUX, ref=2),
    ]
    rel = _relation(members)
    nodes, adj = _build_rail_graph(rel["members"])
    bridged = _bridge_to_named_stops(rel, nodes, adj, *MONTPARNASSE, *BORDEAUX)

    assert bridged <= 2, "more than two invented edges on one graph"
