"""Tests for overpass_service ferry/bus fallback — ensures OverpassError
is raised (not a silent 2-point chord) when no OSM route is found."""

from unittest.mock import patch

import pytest

from src.services.overpass_service import (
    OverpassError,
    get_ferry_geometry,
    get_bus_geometry,
)

# Visby → Nynäshamn coordinates (the reported failing route)
_LAT1, _LON1 = 57.6348, 18.2948
_LAT2, _LON2 = 58.9035, 17.9453


def _empty_overpass(*_args, **_kwargs):
    return {"elements": []}


def _failing_overpass(*_args, **_kwargs):
    raise OverpassError("Overpass timeout")


class TestFerryFallbackRaisesOnMissingRoute:
    def test_no_relation_no_ways_raises(self):
        """Both strategies return empty results → OverpassError, not a chord."""
        with patch("src.services.overpass_service._overpass", side_effect=_empty_overpass):
            with pytest.raises(OverpassError):
                get_ferry_geometry(_LAT1, _LON1, _LAT2, _LON2)

    def test_overpass_failure_raises(self):
        """Overpass network failure → OverpassError propagates."""
        with patch("src.services.overpass_service._overpass", side_effect=_failing_overpass):
            with pytest.raises(OverpassError):
                get_ferry_geometry(_LAT1, _LON1, _LAT2, _LON2)

    def test_result_is_never_two_point_chord(self):
        """On success the polyline has more than 2 points (real OSM geometry)."""
        fake_relation = {
            "type": "relation",
            "members": [
                {
                    "type": "way",
                    "geometry": [
                        {"lon": _LON1, "lat": _LAT1},
                        {"lon": (_LON1 + _LON2) / 2, "lat": (_LAT1 + _LAT2) / 2},
                        {"lon": _LON2, "lat": _LAT2},
                    ],
                }
            ],
        }

        def _overpass_with_relation(*_args, **_kwargs):
            return {"elements": [fake_relation]}

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_with_relation):
            result = get_ferry_geometry(_LAT1, _LON1, _LAT2, _LON2)

        assert len(result) >= 3, "Expected real geometry, not a 2-point chord"


class TestFerryEndpointScoring:
    """Regression for the Visby–Nynäshamn / Oskarshamn–Visby failure.

    The bounding box for long open-sea crossings covers dozens of short
    coastal ferries.  The old scoring (shortest total path length) picked a
    wrong short hop.  The fixed scoring (endpoint proximity) must pick the
    relation whose trimmed endpoints are closest to the requested ports.
    """

    def test_prefers_matching_route_over_shorter_one(self):
        # Requested: Visby → Nynäshamn
        lat1, lon1 = _LAT1, _LON1  # Visby
        lat2, lon2 = _LAT2, _LON2  # Nynäshamn

        # Correct relation: 3 points, endpoints close to the requested ports.
        correct_relation = {
            "type": "relation",
            "members": [{
                "type": "way",
                "geometry": [
                    {"lon": lon1,                      "lat": lat1},
                    {"lon": (lon1 + lon2) / 2,         "lat": (lat1 + lat2) / 2},
                    {"lon": lon2,                      "lat": lat2},
                ],
            }],
        }

        # Wrong relation: shorter total path but endpoints nowhere near the
        # requested ports (simulates a Stockholm archipelago hop).
        wrong_relation = {
            "type": "relation",
            "members": [{
                "type": "way",
                "geometry": [
                    {"lon": 18.07, "lat": 59.32},   # Strömkajen (Stockholm)
                    {"lon": 18.15, "lat": 59.31},
                ],
            }],
        }

        def _overpass_two_rels(*_args, **_kwargs):
            # Wrong relation listed first so old code would have picked it.
            return {"elements": [wrong_relation, correct_relation]}

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_two_rels):
            result = get_ferry_geometry(lat1, lon1, lat2, lon2)

        # The first point of the result must be near Visby, not Stockholm.
        assert abs(result[0][1] - lat1) < 0.1, (
            f"Expected result to start near Visby (lat {lat1}), got {result[0]}"
        )
        assert abs(result[-1][1] - lat2) < 0.1, (
            f"Expected result to end near Nynäshamn (lat {lat2}), got {result[-1]}"
        )

    def test_rejects_relation_when_trimmed_endpoints_too_far(self):
        """Regression for Degerby–Svinö (Åland): the ferry has no route=ferry OSM
        relation.  Strategy A found a different Åland ferry relation whose trimmed
        endpoints were 3–5 km from the query points (score ≈ 0.0047) and returned
        wrong geometry.  The score threshold must reject that relation so strategy C
        (ferry=yes Dijkstra) gets to run instead.
        """
        # Degerby–Svinö query coordinates
        lat1, lon1 = 60.031261, 20.386155   # Degerby terminal
        lat2, lon2 = 60.06677,  20.267276   # Svinö terminal

        # Wrong relation: endpoints 3–5 km off — matches the actual bad data
        # that was stored in production (polyline first/last from the bad DB).
        wrong_relation = {
            "type": "relation",
            "members": [{
                "type": "way",
                "geometry": [
                    {"lon": 20.4033434, "lat": 60.0637562},
                    {"lon": 20.3494846, "lat": 60.0642322},
                    {"lon": 20.3108515, "lat": 60.0287074},
                ],
            }],
        }

        def _overpass_wrong_only(*_args, **_kwargs):
            return {"elements": [wrong_relation]}

        # Strategy A must reject this relation (score >> threshold).
        # Strategy B also returns nothing; strategy C raises (no ferry=yes ways).
        # The whole call must raise OverpassError rather than return wrong geometry.
        with patch("src.services.overpass_service._overpass", side_effect=_overpass_wrong_only):
            with pytest.raises(OverpassError):
                get_ferry_geometry(lat1, lon1, lat2, lon2)


class TestBusFallbackRaisesOnMissingRoute:
    def test_no_ways_raises(self):
        with patch("src.services.overpass_service._overpass", side_effect=_empty_overpass):
            with pytest.raises(OverpassError):
                get_bus_geometry(_LAT1, _LON1, _LAT2, _LON2)
