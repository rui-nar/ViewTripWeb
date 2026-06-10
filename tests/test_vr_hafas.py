"""Tests for VR (Finnish Railways) HAFAS support and the two-endpoint
train route-relation strategy in overpass_service."""

from unittest.mock import patch

import pytest

from src.services.hafas_service import HafasError, get_stop_sequence
from src.services.overpass_service import (
    OverpassError,
    _via_train_relations_endpoints,
    get_rail_geometry,
)

# Helsinki → Oulu representative coordinates
_LAT1, _LON1 = 60.172097, 24.941249   # Helsinki Central Station
_LAT2, _LON2 = 65.010017, 25.484046   # Oulu Station

# Day-88 style: Hanko → Salo
_D88_LAT1, _D88_LON1 = 59.827043, 22.968801
_D88_LAT2, _D88_LON2 = 60.069381, 23.664059


# ---------------------------------------------------------------------------
# VR HAFAS tests
# ---------------------------------------------------------------------------

_VR_STATIONS = [
    {
        "stationShortCode": "HKI",
        "stationName": "Helsinki asema",
        "latitude": 60.172097,
        "longitude": 24.941249,
        "stationUICCode": 1,
        "passengerTraffic": True,
    },
    {
        "stationShortCode": "TPE",
        "stationName": "Tampere asema",
        "latitude": 61.498224,
        "longitude": 23.773087,
        "stationUICCode": 160,
        "passengerTraffic": True,
    },
    {
        "stationShortCode": "OUL",
        "stationName": "Oulu asema",
        "latitude": 65.010017,
        "longitude": 25.484046,
        "stationUICCode": 483,
        "passengerTraffic": True,
    },
]

_VR_TRAIN_SCHEDULE = [
    {
        "trainNumber": 3,
        "departureDate": "2026-06-01",
        "timeTableRows": [
            {"stationShortCode": "HKI", "type": "DEPARTURE"},
            {"stationShortCode": "TPE", "type": "ARRIVAL"},
            {"stationShortCode": "TPE", "type": "DEPARTURE"},
            {"stationShortCode": "OUL", "type": "ARRIVAL"},
        ],
    }
]


class TestVrHafas:
    def _mock_vr(self, mocker=None):
        """Patch _vr_stations_cache and the requests for the schedule."""
        import src.services.hafas_service as svc
        svc._vr_stations_cache = _VR_STATIONS

    def test_vr_returns_stop_sequence(self):
        """get_stop_sequence with provider='vr' returns trimmed stops."""
        import src.services.hafas_service as svc
        svc._vr_stations_cache = _VR_STATIONS

        with patch("src.services.hafas_service.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VR_TRAIN_SCHEDULE
            mock_get.return_value.raise_for_status = lambda: None

            stops = get_stop_sequence(
                provider="vr",
                train_number="3",
                date="2026-06-01",
                start_lat=_LAT1, start_lon=_LON1,
                end_lat=_LAT2,   end_lon=_LON2,
            )

        assert len(stops) >= 2
        # First stop should be Helsinki, last should be Oulu
        assert stops[0]["name"] == "Helsinki asema"
        assert stops[-1]["name"] == "Oulu asema"

        # Reset cache
        svc._vr_stations_cache = None

    def test_vr_strips_prefix_from_train_number(self):
        """'IC 3' is normalised to '3' before the API call."""
        import src.services.hafas_service as svc
        svc._vr_stations_cache = _VR_STATIONS

        with patch("src.services.hafas_service.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VR_TRAIN_SCHEDULE
            mock_get.return_value.raise_for_status = lambda: None

            stops = get_stop_sequence(
                provider="vr",
                train_number="IC 3",
                date="2026-06-01",
                start_lat=_LAT1, start_lon=_LON1,
                end_lat=_LAT2,   end_lon=_LON2,
            )

        # Check the URL called had the numeric-only train number
        called_url = mock_get.call_args[0][0]
        assert called_url.endswith("/trains/2026-06-01/3"), called_url

        svc._vr_stations_cache = None

    def test_vr_train_not_found_raises(self):
        """Empty schedule list raises HafasError."""
        import src.services.hafas_service as svc
        svc._vr_stations_cache = _VR_STATIONS

        with patch("src.services.hafas_service.requests.get") as mock_get:
            mock_get.return_value.json.return_value = []
            mock_get.return_value.raise_for_status = lambda: None

            with pytest.raises(HafasError, match="not found"):
                get_stop_sequence(
                    provider="vr",
                    train_number="999",
                    date="2026-06-01",
                    start_lat=_LAT1, start_lon=_LON1,
                    end_lat=_LAT2,   end_lon=_LON2,
                )

        svc._vr_stations_cache = None

    def test_vr_deduplicates_arrival_departure_rows(self):
        """Each station appears only once even though schedule has ARRIVAL+DEPARTURE."""
        import src.services.hafas_service as svc
        svc._vr_stations_cache = _VR_STATIONS

        with patch("src.services.hafas_service.requests.get") as mock_get:
            mock_get.return_value.json.return_value = _VR_TRAIN_SCHEDULE
            mock_get.return_value.raise_for_status = lambda: None

            stops = get_stop_sequence(
                provider="vr",
                train_number="3",
                date="2026-06-01",
                start_lat=_LAT1, start_lon=_LON1,
                end_lat=_LAT2,   end_lon=_LON2,
            )

        names = [s["name"] for s in stops]
        # Tampere should appear exactly once despite two timeTableRows
        assert names.count("Tampere asema") == 1

        svc._vr_stations_cache = None


# ---------------------------------------------------------------------------
# Two-endpoint train route-relation intersection tests
# ---------------------------------------------------------------------------

def _make_relation(lon_start, lat_start, lon_end, lat_end, mid_count=1):
    """Build a fake Overpass relation element."""
    geom = [{"lon": lon_start, "lat": lat_start}]
    for i in range(1, mid_count + 1):
        f = i / (mid_count + 1)
        geom.append({"lon": lon_start + f * (lon_end - lon_start),
                     "lat": lat_start + f * (lat_end - lat_start)})
    geom.append({"lon": lon_end, "lat": lat_end})
    return {"type": "relation", "id": 1, "members": [{"type": "way", "geometry": geom}]}


class TestTrainRelationsEndpoints:
    def test_finds_relation_covering_both_endpoints(self):
        """Strategy B returns geometry for a relation near both endpoints."""
        good_rel = _make_relation(_LON1, _LAT1, _LON2, _LAT2, mid_count=3)
        good_rel["id"] = 42

        # Both endpoint queries return the same relation ID.
        def _overpass_side_effect(query):
            if "out ids" in query:
                return {"elements": [{"id": 42}]}
            # Geometry fetch
            return {"elements": [good_rel]}

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_side_effect):
            result = _via_train_relations_endpoints([
                {"lat": _LAT1, "lon": _LON1},
                {"lat": _LAT2, "lon": _LON2},
            ])

        assert len(result) >= 3
        # First point near start, last near end
        assert abs(result[0][1] - _LAT1) < 0.2
        assert abs(result[-1][1] - _LAT2) < 0.2

    def test_raises_when_no_common_relation(self):
        """No intersection → OverpassError, not a 2-point chord."""
        call_count = [0]

        def _overpass_side_effect(query):
            call_count[0] += 1
            if "out ids" in query:
                # First query returns id=1, second returns id=2 — no overlap.
                return {"elements": [{"id": call_count[0]}]}
            return {"elements": []}

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_side_effect):
            with pytest.raises(OverpassError, match="No train route relation serves both"):
                _via_train_relations_endpoints([
                    {"lat": _LAT1, "lon": _LON1},
                    {"lat": _LAT2, "lon": _LON2},
                ])

    def test_raises_when_endpoints_too_far(self):
        """Relation found but its geometry doesn't match the query endpoints."""
        wrong_rel = _make_relation(18.0, 59.0, 18.5, 59.5, mid_count=2)
        wrong_rel["id"] = 99

        def _overpass_side_effect(query):
            if "out ids" in query:
                return {"elements": [{"id": 99}]}
            return {"elements": [wrong_rel]}

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_side_effect):
            with pytest.raises(OverpassError, match="endpoints close enough"):
                _via_train_relations_endpoints([
                    {"lat": _LAT1, "lon": _LON1},
                    {"lat": _LAT2, "lon": _LON2},
                ])

    def test_get_rail_geometry_uses_strategy_b_when_uic_fails(self):
        """get_rail_geometry falls through to Strategy B when UIC enrichment fails."""
        good_rel = _make_relation(_LON1, _LAT1, _LON2, _LAT2, mid_count=3)
        good_rel["id"] = 42

        def _overpass_side_effect(query):
            # UIC enrichment queries return empty (no stations found).
            if "railway" in query and "uic_ref" in query:
                return {"elements": []}
            if "out ids" in query:
                return {"elements": [{"id": 42}]}
            return {"elements": [good_rel]}

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_side_effect):
            result = get_rail_geometry([
                {"lat": _LAT1, "lon": _LON1},
                {"lat": _LAT2, "lon": _LON2},
            ])

        assert len(result) >= 3

    def test_get_rail_geometry_only_enriches_endpoints(self):
        """With N>2 stops, only first and last are enriched — not all N stops.

        VR returns uic='' for every stop; enriching all N triggers O(N) Overpass
        calls that cumulatively exceed the nginx proxy timeout on long routes
        like Helsinki→Rovaniemi.
        """
        good_rel = _make_relation(_LON1, _LAT1, _LON2, _LAT2, mid_count=3)
        good_rel["id"] = 42
        enrich_calls: list[str] = []

        def _overpass_side_effect(query):
            if "railway" in query and "uic_ref" in query:
                enrich_calls.append(query)
                return {"elements": []}  # no UIC found → falls through to B
            if "out ids" in query:
                return {"elements": [{"id": 42}]}
            return {"elements": [good_rel]}

        many_stops = [
            {"lat": _LAT1, "lon": _LON1},
            {"lat": 62.0,  "lon": 25.0},   # intermediate — must NOT be enriched
            {"lat": 63.5,  "lon": 25.2},   # intermediate — must NOT be enriched
            {"lat": _LAT2, "lon": _LON2},
        ]

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_side_effect):
            result = get_rail_geometry(many_stops)

        # Exactly 2 enrichment calls (first + last), not 4.
        assert len(enrich_calls) == 2, f"Expected 2 enrichment calls, got {len(enrich_calls)}"
        assert len(result) >= 3


class TestCoordinateFallbackBoundedCalls:
    """Regression for the Helsinki–Rovaniemi multi-minute hang.

    When strategies A/B fail (no UIC, no covering route relation — common in
    Finland), resolution falls to the coordinate Dijkstra fallback. That used
    to issue one Overpass request *per consecutive stop pair*, so a ~20-stop
    route fired ~20 sequential 45 s-timeout requests. The fallback must now make
    a single whole-route query regardless of stop count.
    """

    def test_strategy_c_makes_single_overpass_query_for_long_route(self):
        n = 12
        stops = [
            {
                "lat": _LAT1 + (i / (n - 1)) * (_LAT2 - _LAT1),
                "lon": _LON1 + (i / (n - 1)) * (_LON2 - _LON1),
            }
            for i in range(n)
        ]

        # One fake railway way through every stop, so the shared-graph Dijkstra
        # connects each consecutive pair.
        rail_way = {
            "type": "way",
            "geometry": [{"lon": s["lon"], "lat": s["lat"]} for s in stops],
        }
        calls = {"enrich": 0, "ids": 0, "rail": 0, "total": 0}

        def _overpass_side_effect(query):
            calls["total"] += 1
            if "uic_ref" in query:        # endpoint UIC enrichment
                calls["enrich"] += 1
                return {"elements": []}   # no station → no UIC → skip Strategy A
            if "out ids" in query:        # Strategy B relation-id lookup
                calls["ids"] += 1
                return {"elements": []}   # none → Strategy B fails → Strategy C
            calls["rail"] += 1            # the single coordinate-fallback query
            return {"elements": [rail_way]}

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_side_effect):
            result = get_rail_geometry(stops)

        # Exactly one whole-route query, regardless of the 12 stops.
        assert calls["rail"] == 1, f"Expected 1 rail query, got {calls['rail']}"
        # Whole resolution stays bounded (2 enrich + 1 Strategy-B id + 1 rail).
        assert calls["total"] <= 4, f"Expected <=4 Overpass calls, got {calls['total']}"
        assert len(result) >= 2

    def test_oversized_bbox_straight_lines_without_query(self):
        """A pathologically long span skips the query and returns a chord."""
        stops = [
            {"lat": 0.0, "lon": 0.0},
            {"lat": 40.0, "lon": 5.0},   # >12° span
        ]
        calls = {"rail": 0}

        def _overpass_side_effect(query):
            if "uic_ref" in query:
                return {"elements": []}
            if "out ids" in query:
                return {"elements": []}
            calls["rail"] += 1
            return {"elements": []}

        with patch("src.services.overpass_service._overpass", side_effect=_overpass_side_effect):
            result = get_rail_geometry(stops)

        assert calls["rail"] == 0, "Oversized bbox must not issue a rail query"
        assert result == [[0.0, 0.0], [5.0, 40.0]]
