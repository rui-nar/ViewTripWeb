"""Route relations: which members are the path, and which relation is the leg (#359).

Paris Gare de l'Est → Strasbourg resolved with its start 13.9 km south of the
station. The cause was not the local rail store — the same resolve against live
Overpass returned a byte-identical wrong answer — but the relation strategies
themselves, in three layers:

1. every member way went into the routing graph, including the station's
   ``railway=platform`` way. A platform is not track, is not connected to track,
   and lies exactly where a leg begins, so it captured the endpoint snap and
   stranded Dijkstra on a closed ring. Every *correct* relation was then
   rejected as disconnected;
2. strategy A took ``elements[0]`` and gave up, so 31 usable candidates were
   never looked at;
3. the relation that did win served other stations entirely, and the guard that
   should have refused it — ``_MAX_SCORE = 0.05``, commented "≈ ~5 km" — was
   really 24.9 km.

Geometry here is Overpass ``out geom`` shape, which is what the store returns
too, so these cover both sources at once.
"""
import math

import pytest

from src.services.overpass_service import (
    OverpassError,
    _ENDPOINT_TOLERANCE_KM,
    _best_relation_geometry,
    _crow_km,
    _endpoints_near,
    _extract_relation_geometry,
    _is_route_path,
    _route_relation_segment,
    _via_train_relations_endpoints,
)

# Paris Gare de l'Est and Strasbourg-Ville, the reported leg.
START = (48.8768, 2.3590)
END = (48.5850, 7.7345)


def _geom(*points):
    return [{"lat": lat, "lon": lon} for lat, lon in points]


def _way(ref, points, role=""):
    return {"type": "way", "ref": ref, "role": role, "geometry": _geom(*points)}


def _relation(rel_id, members, name="test"):
    return {"type": "relation", "id": rel_id, "tags": {"route": "train", "name": name},
            "members": members, "missing_members": 0}


# The track, in three member ways that share their end vertices — the only thing
# that joins ways in `_build_rail_graph`. It starts 189 m north of the station,
# so anything sitting closer wins the endpoint snap.
TRACK_START = (48.8785, 2.3590)
TRACK = [
    _way(1, [TRACK_START, (48.8000, 3.5000)]),
    _way(2, [(48.8000, 3.5000), (48.7000, 5.0000)]),
    _way(3, [(48.7000, 5.0000), END]),
]

# A closed ring 50 m from the station, touching no track: a platform, as OSM
# maps one. `way 86199268 "Voies 27 & 28"` at Gare de l'Est is exactly this.
PLATFORM = _way(9, [(48.8772, 2.3592), (48.8772, 2.3596),
                    (48.8774, 2.3596), (48.8774, 2.3592), (48.8772, 2.3592)],
                role="platform")


def _start_offset_km(poly):
    return _crow_km(START[0], START[1], poly[0][1], poly[0][0])


# ---------------------------------------------------------------------------
# 1 — the platform must not be in the routing graph
# ---------------------------------------------------------------------------

def test_a_platform_at_the_origin_does_not_capture_the_endpoint_snap():
    """The #359 shape: platform nearer than track, and unreachable from it.

    Without the role filter the nearest node is on the ring, the ring reaches
    nothing, and the whole relation is thrown away as disconnected — which is
    how a correct Paris Est ↔ Strasbourg relation lost to one that stops 14 km
    south of the station.
    """
    rel = _relation(1, [PLATFORM, *TRACK])
    poly = _extract_relation_geometry(rel, *START, *END)

    assert poly is not None, "the platform stranded Dijkstra on a closed ring"
    assert _start_offset_km(poly) < 0.3
    assert _crow_km(END[0], END[1], poly[-1][1], poly[-1][0]) < 0.1
    # And not one vertex of the ring is on the line.
    assert not ({(p["lat"], p["lon"]) for p in PLATFORM["geometry"]}
                & {(p[1], p[0]) for p in poly})


@pytest.mark.parametrize("role", ["platform", "platform_entry_only",
                                  "platform_exit_only", "hail_and_ride"])
def test_every_platform_role_is_excluded(role):
    assert not _is_route_path(role)
    rel = _relation(1, [dict(PLATFORM, role=role), *TRACK])
    assert _extract_relation_geometry(rel, *START, *END) is not None


@pytest.mark.parametrize("role", ["", "forward", "backward", "alternative"])
def test_a_non_platform_role_is_still_the_path(role):
    """The filter must be a deny-list, never an allow-list of the empty role.

    2,299 of France's 681,815 way members carry `forward`, `backward` or
    `alternative`, and every one of them is track the route runs on. Dropping
    the middle of this relation because it is labelled breaks the chain, and a
    broken chain is a rejected relation — the very failure being fixed.
    """
    assert _is_route_path(role)
    middle = dict(TRACK[1], role=role)
    rel = _relation(1, [TRACK[0], middle, TRACK[2]])

    poly = _extract_relation_geometry(rel, *START, *END)
    assert poly is not None, f"role {role!r} was dropped as if it were a platform"
    assert _crow_km(END[0], END[1], poly[-1][1], poly[-1][0]) < 0.1


# ---------------------------------------------------------------------------
# 2 — a relation genuinely disconnected upstream still yields its route
# ---------------------------------------------------------------------------

def test_a_stub_disconnected_in_osm_does_not_reject_the_whole_relation():
    """Paris Montparnasse → Bordeaux: no platform involved, still two components.

    A 322-node island covering the station throat is simply not joined to the
    main line in OSM's membership. Snapping each endpoint independently puts
    them in different components and Dijkstra reports no path, so the correct
    relation loses to whatever else scores. Snapping inside one component
    returns the main line — short at the start, which is honest, and which the
    endpoint tolerance still has to accept or refuse on its own terms.
    """
    stub = _way(8, [(48.8768, 2.3590), (48.8700, 2.3600)])   # touches no track
    rel = _relation(1, [stub, *TRACK])

    poly = _extract_relation_geometry(rel, *START, *END)
    assert poly is not None
    # The main line, not the stub: it reaches Strasbourg.
    assert _crow_km(END[0], END[1], poly[-1][1], poly[-1][0]) < 0.1
    assert _start_offset_km(poly) == pytest.approx(0.189, abs=0.05)


def test_a_relation_with_no_through_line_is_still_rejected():
    """Two stubs and nothing joining them — the leg is not on this relation.

    Snapping inside one component means the relation now yields its best
    *piece*, which here is an 800 m stub at the origin rather than None. That is
    the deliberate trade for the case above, and it is why the endpoint
    tolerance is the thing that decides: what a caller may ship is what
    ``_best_relation_geometry`` returns, never the raw extraction.
    """
    rel = _relation(1, [_way(8, [(48.8768, 2.3590), (48.8700, 2.3600)]),
                        _way(9, [END, (48.5900, 7.7400)])])

    stub = _extract_relation_geometry(rel, *START, *END)
    assert _crow_km(END[0], END[1], stub[-1][1], stub[-1][0]) > 100

    assert _best_relation_geometry([rel], *START, *END) is None


# ---------------------------------------------------------------------------
# 3 — the leg is chosen by where the line actually runs
# ---------------------------------------------------------------------------

def _wrong_station_relation(rel_id, offset_deg):
    """A relation that routes perfectly, starting *offset_deg* south of START.

    The #359 winner in miniature: `TGV InOui 061C : Strasbourg → Aéroport
    Charles de Gaulle` is a real, connected, plausible-length route. It simply
    does not call at Gare de l'Est.
    """
    origin = (START[0] - offset_deg, START[1])
    return _relation(rel_id, [
        _way(21, [origin, (48.7000, 5.0000)]),
        _way(22, [(48.7000, 5.0000), END]),
    ], name="serves other stations")


def test_a_relation_that_runs_between_other_stations_is_refused():
    far = _wrong_station_relation(5935098, 0.125)      # ~13.9 km south, as reported
    poly = _extract_relation_geometry(far, *START, *END)
    assert poly is not None, "the candidate itself routes fine — that is the trap"
    assert _start_offset_km(poly) > 13

    assert _best_relation_geometry([far], *START, *END) is None


def test_the_tolerance_is_kilometres_not_squared_degrees():
    """Pins the unit, which is the whole of the #359 guard failure.

    The predecessor was `_MAX_SCORE = 0.05` in squared degrees, commented
    "≈ both endpoints within ~5 km". sqrt(0.05) is 0.2236°, or 24.9 km — five
    times what the comment claimed, and enough to pass a line starting 13.9 km
    from the station. A test that only checked "far is refused" would pass on
    the broken constant too, so check both sides of the stated boundary.
    """
    assert _ENDPOINT_TOLERANCE_KM == 5.0

    inside = _wrong_station_relation(1, 0.036)         # ~4.0 km
    outside = _wrong_station_relation(2, 0.054)        # ~6.0 km
    assert 3.5 < _start_offset_km(_extract_relation_geometry(inside, *START, *END)) < 4.5
    assert 5.5 < _start_offset_km(_extract_relation_geometry(outside, *START, *END)) < 6.5

    assert _best_relation_geometry([inside], *START, *END) is not None
    assert _best_relation_geometry([outside], *START, *END) is None


def test_endpoints_near_measures_both_ends():
    good = [[START[1], START[0]], [END[1], END[0]]]
    assert _endpoints_near(good, *START, *END)
    assert not _endpoints_near([[START[1], START[0]], [5.0, 48.0]], *START, *END)
    assert not _endpoints_near([[5.0, 48.0], [END[1], END[0]]], *START, *END)


# ---------------------------------------------------------------------------
# 4 — strategy A scores every candidate, not just the first
# ---------------------------------------------------------------------------

class _Source:
    """Just enough RailSource to drive the two relation strategies."""

    def __init__(self, relations):
        self.relations = relations

    def relations_for_uic_pair(self, uic1, uic2, near):
        return list(self.relations)

    def relations_near(self, lat, lon, radius_m=25_000):
        return {rel["id"] for rel in self.relations}

    def relation_geometry(self, rel_ids, near):
        wanted = set(rel_ids)
        return [rel for rel in self.relations if rel["id"] in wanted]

    def nearest_station(self, lat, lon, radius_m=5000):    # pragma: no cover
        return None

    def ways_in_bbox(self, *box):                          # pragma: no cover
        return []


def test_strategy_a_looks_past_an_unroutable_first_candidate():
    """`elements[0]` is the lowest relation id, which means nothing about quality.

    On the reported leg it was `5920986`, whose graph does not route, while
    `5922256`, `5945360` and 29 others sat behind it untouched.
    """
    candidates = [
        _relation(10, [_way(31, [START, (48.87, 2.40)]),
                       _way(32, [(48.60, 7.70), END])], name="disconnected"),
        _wrong_station_relation(11, 0.125),
        _relation(12, [PLATFORM], name="platform only"),
        _relation(13, [PLATFORM, *TRACK], name="the right one"),
    ]
    stops = ({"lat": START[0], "lon": START[1], "uic": "8711300"},
             {"lat": END[0], "lon": END[1], "uic": "8721202"})

    poly = _route_relation_segment(*stops, source=_Source(candidates))
    assert poly is not None
    assert _start_offset_km(poly) < 0.3
    assert _crow_km(END[0], END[1], poly[-1][1], poly[-1][0]) < 0.1


def test_strategy_a_returns_none_when_no_candidate_serves_the_pair():
    stops = ({"lat": START[0], "lon": START[1], "uic": "8711300"},
             {"lat": END[0], "lon": END[1], "uic": "8721202"})
    source = _Source([_wrong_station_relation(11, 0.125)])
    assert _route_relation_segment(*stops, source=source) is None


def test_strategy_b_refuses_a_relation_serving_other_stations():
    """Strategy B is the fallback that shipped the wrong line; same judge now."""
    stops = [{"lat": START[0], "lon": START[1]}, {"lat": END[0], "lon": END[1]}]
    source = _Source([_wrong_station_relation(5935098, 0.125)])

    with pytest.raises(OverpassError, match="runs between the two stops"):
        _via_train_relations_endpoints(stops, source=source)


def test_strategy_b_accepts_the_relation_that_does_serve_them():
    stops = [{"lat": START[0], "lon": START[1]}, {"lat": END[0], "lon": END[1]}]
    source = _Source([_wrong_station_relation(5935098, 0.125),
                      _relation(5945360, [PLATFORM, *TRACK], name="the right one")])

    poly = _via_train_relations_endpoints(stops, source=source)
    assert _start_offset_km(poly) < 0.3


def test_the_best_of_several_acceptable_candidates_wins():
    near = _wrong_station_relation(1, 0.009)       # ~1 km out, inside tolerance
    exact = _relation(2, [PLATFORM, *TRACK])
    for order in ([near, exact], [exact, near]):
        poly = _best_relation_geometry(order, *START, *END)
        assert _start_offset_km(poly) < 0.3, "the closer candidate must win either way"


def test_candidate_scoring_is_bounded():
    """One query returns every candidate, so this bounds CPU rather than requests —
    but it still has to bound it: 300 relations is 300 Dijkstra runs."""
    from src.services.overpass_service import _MAX_RELATION_CANDIDATES

    seen = []

    class _Counting(_Source):
        def relation_geometry(self, rel_ids, near):
            seen.append(len(list(rel_ids)))
            return super().relation_geometry(rel_ids, near)

    source = _Counting([_relation(i, [*TRACK]) for i in range(100)])
    stops = [{"lat": START[0], "lon": START[1]}, {"lat": END[0], "lon": END[1]}]
    _via_train_relations_endpoints(stops, source=source)
    assert seen == [_MAX_RELATION_CANDIDATES]


def test_a_candidate_without_a_role_key_is_treated_as_path():
    """A schema 1 store, and any hand-built element, omits the role entirely.

    It must read as "path", which is the pre-#359 behaviour — not as "unknown,
    therefore drop", which would empty every relation a schema 1 file serves.
    """
    rel = _relation(1, [{k: v for k, v in way.items() if k != "role"}
                        for way in TRACK])
    assert _extract_relation_geometry(rel, *START, *END) is not None
