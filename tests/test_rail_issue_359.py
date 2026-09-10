"""The reported leg, on the real data that got it wrong (#359).

Paris Gare de l'Est → Strasbourg resolved with its start 13.9 km south of the
station. This is that resolve, against the two relations actually involved,
trimmed out of the published France extract:

* **5920986** — ``TGV InOui 661A / ICE 83 : Stuttgart → Karlsruhe → Strasbourg
  → Paris Est``. Strategy A's ``elements[0]`` for this UIC pair, i.e. the
  relation the resolver reached for first and threw away.
* **5935098** — ``TGV InOui 061C : Strasbourg → Aéroport Charles de Gaulle``.
  What shipped instead. A real, connected, plausible-length route that simply
  does not call at Gare de l'Est: its Paris end is on the Grande Ceinture,
  13.9 km south.

The trap is in the data, not in the arrangement of this test, and
:func:`test_the_fixture_still_contains_the_trap` asserts that it is — so a
future refresh of the fixture cannot quietly turn this into a test of nothing.
"""
import json
import os

import pytest

from src.services.overpass_service import (
    _best_relation_geometry,
    _build_rail_graph,
    _components,
    _crow_km,
    _extract_relation_geometry,
    _nearest_node,
    _polyline_km,
)

FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "rail", "issue-359-relations.json")

# The stops as `_enrich_uic` leaves them: snapped to the OSM station nodes.
GARE_DE_L_EST = (48.8770979, 2.3594905)
STRASBOURG = (48.5852933, 7.7339249)

RIGHT_RELATION = 5920986
WRONG_RELATION = 5935098


@pytest.fixture(scope="module")
def relations():
    with open(FIXTURE, encoding="utf-8") as handle:
        return json.load(handle)


def _by_id(relations, rel_id):
    return next(r for r in relations if r["id"] == rel_id)


def _offsets_km(poly):
    return (_crow_km(*GARE_DE_L_EST, poly[0][1], poly[0][0]),
            _crow_km(*STRASBOURG, poly[-1][1], poly[-1][0]))


# ---------------------------------------------------------------------------
# The fixture really is the failing case
# ---------------------------------------------------------------------------

def test_the_fixture_still_contains_the_trap(relations):
    """Held platform members, and one of them nearer the station than any track.

    That is the whole bug in two facts. If a refreshed fixture ever loses
    either, every other assertion here would pass on a resolver with the fix
    reverted, and the regression would be back with a green suite.
    """
    rel = _by_id(relations, RIGHT_RELATION)
    platforms = [m for m in rel["members"] if m["role"].startswith("platform")]
    assert platforms, "the fixture no longer carries the platform members"

    # Build the graph the pre-#359 resolver built: every member way, roles
    # ignored. The node nearest the station is on a platform, and its component
    # is a handful of vertices going nowhere.
    nodes, adj = _build_rail_graph(
        [m for m in rel["members"] if len(m["geometry"]) >= 2])
    snapped = _nearest_node(nodes, *GARE_DE_L_EST)
    island = next(c for c in _components(nodes, adj) if snapped in c)

    assert len(island) < 20, "the endpoint no longer snaps onto a stranded ring"
    platform_vertices = {(p["lat"], p["lon"])
                         for m in platforms for p in m["geometry"]}
    assert (nodes[snapped][1], nodes[snapped][0]) in platform_vertices


# ---------------------------------------------------------------------------
# …and it now resolves to the line the traveller took
# ---------------------------------------------------------------------------

def test_the_right_relation_routes_from_the_platform_it_actually_leaves_from(relations):
    poly = _extract_relation_geometry(
        _by_id(relations, RIGHT_RELATION), *GARE_DE_L_EST, *STRASBOURG)

    assert poly is not None, "the platform stranded Dijkstra again"
    start_km, end_km = _offsets_km(poly)
    assert start_km < 0.5, f"starts {start_km * 1000:.0f} m from Gare de l'Est"
    assert end_km < 0.5
    # The LGV Est is ~440 km. The line that shipped was 492 km via the Ceinture.
    assert 420 < _polyline_km(poly) < 460


def test_the_relation_that_shipped_is_refused(relations):
    """It routes perfectly. It just does not go to Gare de l'Est.

    ``_rail_length_ok`` cannot catch this — 492 km against a 380 km crow is a
    perfectly plausible detour ratio — and the old ``_MAX_SCORE`` could not
    either, being 24.9 km wide. Only an endpoint check does.
    """
    wrong = _by_id(relations, WRONG_RELATION)
    poly = _extract_relation_geometry(wrong, *GARE_DE_L_EST, *STRASBOURG)

    start_km, end_km = _offsets_km(poly)
    assert 13 < start_km < 15, "this is the 13.9 km reported in the issue"
    assert end_km < 0.5, "the Strasbourg end was always right"

    assert _best_relation_geometry([wrong], *GARE_DE_L_EST, *STRASBOURG) is None


@pytest.mark.parametrize("order", [[RIGHT_RELATION, WRONG_RELATION],
                                   [WRONG_RELATION, RIGHT_RELATION]])
def test_the_leg_resolves_to_gare_de_l_est_whichever_candidate_comes_first(
        relations, order):
    """Candidate order is relation id order, which means nothing about quality —
    on the real leg the wrong one sorted first among 32."""
    poly = _best_relation_geometry(
        [_by_id(relations, rel_id) for rel_id in order],
        *GARE_DE_L_EST, *STRASBOURG)

    assert poly is not None
    start_km, _ = _offsets_km(poly)
    assert start_km < 0.5, f"issue #359: the leg starts {start_km:.1f} km away"
