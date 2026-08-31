"""Tests for MOTIS/Transitous train route resolution (issue #277).

The fixtures under ``tests/fixtures/motis_*.json`` are **real** responses
recorded from https://api.transitous.org (the departure-board entries keep only
the fields the service reads, so the files stay a readable size; nothing else is
altered). No test here touches the network.

The regression this file exists for: a Hamburg Hbf → Offenburg segment on
"ICE 75" could not be resolved. The old code asked a *journey planner* for 15
results from a hardcoded 06:00 and passed a ``lineName`` parameter that route
does not accept — ICE 75 leaves Hamburg at 14:29 with 275 rail departures ahead
of it, so it was unfindable. Matching now happens on a departure board.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from unittest.mock import patch

import pytest

import src.services.hafas_service as svc
from src.services.hafas_service import HafasError, get_train_route

_FIXTURES = Path(__file__).parent / "fixtures"

# Segment endpoints as a user would place them: the issue's Hamburg Hbf pin and
# Offenburg town centre (~700 m from the station, so trimming has to snap).
_HH_LAT, _HH_LON = 53.5528, 10.0067
_OG_LAT, _OG_LON = 48.4711, 7.9447
_BASEL_LAT, _BASEL_LON = 47.5474, 7.5895   # the trip's real terminus
_DATE = "2026-09-01"


def _fx(name: str):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def _km(lat1, lon1, lat2, lon2) -> float:
    dlat = (lat1 - lat2) * 111.0
    dlon = (lon1 - lon2) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)


class _Resp:
    def __init__(self, payload, status=200):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


def _geocodes() -> dict:
    """Recorded reverse-geocode responses, keyed by the ``place`` MOTIS is sent."""
    return {
        f"{_HH_LAT},{_HH_LON}": _fx("motis_reverse_geocode_hamburg.json"),
        f"{_OG_LAT},{_OG_LON}": _fx("motis_reverse_geocode_offenburg.json"),
    }


class _Motis:
    """Stand-in for the live MOTIS API, recording every request it serves."""

    def __init__(self, geocode=None, boards=None, trip=None, statuses=None):
        self.geocode = geocode if geocode is not None else _geocodes()
        self.boards = boards if boards is not None else [_fx("motis_stoptimes_hamburg.json")]
        self.trip = trip if trip is not None else _fx("motis_trip_ice75.json")
        self.statuses = list(statuses or [])   # queued HTTP statuses to serve first
        self.calls: list[tuple[str, dict]] = []
        self._board_i = 0

    def __call__(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        if self.statuses:
            return _Resp(None, self.statuses.pop(0))
        if url.endswith("/reverse-geocode"):
            if isinstance(self.geocode, dict):
                return _Resp(self.geocode.get(params["place"], []))
            return _Resp(self.geocode)
        if url.endswith("/stoptimes"):
            board = self.boards[min(self._board_i, len(self.boards) - 1)]
            self._board_i += 1
            return _Resp(board)
        if url.endswith("/trip"):
            return _Resp(self.trip)
        raise AssertionError(f"unexpected MOTIS request: {url}")

    def paths(self) -> list[str]:
        return [u.rsplit("/", 1)[-1] for u, _ in self.calls]

    def params_for(self, path: str) -> dict:
        return next(p for u, p in self.calls if u.endswith(path))


@pytest.fixture(autouse=True)
def _clear_stop_cache():
    svc._nearest_stop_cached.cache_clear()
    yield
    svc._nearest_stop_cached.cache_clear()


@pytest.fixture(autouse=True)
def _no_real_backoff():
    """Keep the retry tests instant — the backoff itself is asserted separately."""
    with patch("src.services.hafas_service.time.sleep") as sleep:
        yield sleep


def _resolve(**kwargs):
    args = dict(train_number="ICE 75", date=_DATE,
                start_lat=_HH_LAT, start_lon=_HH_LON,
                end_lat=_OG_LAT, end_lon=_OG_LON)
    args.update(kwargs)
    return get_train_route(**args)


# ---------------------------------------------------------------------------
# The reported bug
# ---------------------------------------------------------------------------

class TestIssue277HamburgOffenburg:
    def test_ice75_resolves_with_offenburg_in_the_stop_sequence(self):
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            route = _resolve()

        names = [s["name"] for s in route.stops]
        assert names[0] == "Hamburg Hbf"
        assert names[-1] == "Offenburg Bahnhof"
        assert "Frankfurt (Main) Hauptbahnhof" in names
        # Trimmed to the user's own leg — the trip itself runs on to Basel.
        assert "Basel SBB" not in names
        assert len(names) == len(set(names))

    def test_polyline_is_real_track_not_a_two_point_chord(self):
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            route = _resolve()

        assert len(route.polyline) > 5000, "expected real track geometry"
        # [lon, lat] like every other polyline in this codebase.
        lon, lat = route.polyline[0]
        assert 9.5 < lon < 10.5 and 53.0 < lat < 54.0
        assert _km(_HH_LAT, _HH_LON, lat, lon) < 2.0
        lon, lat = route.polyline[-1]
        assert _km(_OG_LAT, _OG_LON, lat, lon) < 2.0

        # …and it follows the line rather than cutting across it: 700+ km of
        # track for a ~530 km crow-flies leg.
        length = sum(
            _km(a[1], a[0], b[1], b[0])
            for a, b in zip(route.polyline, route.polyline[1:])
        )
        assert 600 < length < 900

    def test_three_requests_and_no_journey_planner(self):
        """One reverse-geocode, one board, one trip — and never /journeys."""
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            _resolve()

        assert api.paths() == ["reverse-geocode", "stoptimes", "trip"]
        assert not any("journeys" in url for url, _ in api.calls)
        assert not any("lineName" in params for _, params in api.calls)

    def test_sends_an_identifying_user_agent(self):
        """Transitous' usage policy asks API clients to identify themselves."""
        seen = {}

        def _capture(url, params=None, headers=None, timeout=None):
            seen.update(headers or {})
            return _Motis()(url, params=params, headers=headers, timeout=timeout)

        with patch("src.services.hafas_service.requests.get", _capture):
            _resolve()
        assert "ViewTripWeb" in seen["User-Agent"]


# ---------------------------------------------------------------------------
# The time-window bug: results=15 from a hardcoded 06:00
# ---------------------------------------------------------------------------

class TestServiceDayWindow:
    def test_mid_afternoon_departure_is_found(self):
        """ICE 75 sits 275 entries deep on the real board and must still match.

        This is exactly what ``results=15`` from a hardcoded 06:00 could never
        reach. (The board's first ICE 75 entry is the 12:21 Hamburg Dammtor
        call — the radius sweep sees it — and the trip then trims to the
        14:29 Hamburg Hbf departure the user actually took.)
        """
        board = _fx("motis_stoptimes_hamburg.json")
        index = next(i for i, e in enumerate(board["stopTimes"])
                     if e.get("tripShortName") == "ICE 75")
        assert index > 250, "fixture must reproduce the deep-in-the-day case"
        assert board["stopTimes"][index]["place"]["departure"] == "2026-09-01T12:21:00Z"

        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            route = _resolve()
        assert route.stops[-1]["name"] == "Offenburg Bahnhof"

    def test_board_is_requested_from_the_start_of_the_local_service_day(self):
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            _resolve()

        params = api.params_for("/stoptimes")
        # 3 h before 00:00 UTC — local midnight anywhere in UTC+1…+3. Not the
        # old hardcoded "{date}T06:00:00+01:00".
        assert params["time"] == "2026-08-31T21:00:00Z"
        assert params["n"] == 500
        assert params["radius"] == 2000

    def test_window_covers_the_whole_local_day(self):
        start, end = svc._service_window(_DATE)
        assert start.isoformat() == "2026-08-31T21:00:00+00:00"
        assert end.isoformat() == "2026-09-02T00:00:00+00:00"
        # Berlin (UTC+2 in September) local day = 31st 22:00Z → 1st 22:00Z.
        assert start.isoformat() <= "2026-08-31T22:00:00+00:00"
        assert end.isoformat() >= "2026-09-01T22:00:00+00:00"

    def test_stops_paging_once_the_board_runs_past_the_service_day(self):
        """A train that isn't running today must not be chased into tomorrow."""
        board = _fx("motis_stoptimes_hamburg.json")
        board["stopTimes"] = [e for e in board["stopTimes"]
                              if e.get("tripShortName") != "ICE 75"]
        # The real board keeps going into the next service day; a match found
        # there would be the wrong day's train, so the scan must stop first.
        tomorrow = json.loads(json.dumps(board["stopTimes"][-1]))
        tomorrow["place"]["departure"] = "2026-09-02T12:29:00Z"
        tomorrow["tripShortName"] = tomorrow["routeShortName"] = "ICE 75"
        tomorrow["tripId"] = "wrong-day"
        board["stopTimes"].append(tomorrow)

        api = _Motis(boards=[board])
        with patch("src.services.hafas_service.requests.get", api):
            with pytest.raises(HafasError, match="not found departing"):
                _resolve()
        assert api.paths().count("stoptimes") == 1

    def test_pages_forward_with_the_cursor_when_the_day_is_not_covered(self):
        board = _fx("motis_stoptimes_hamburg.json")
        head = dict(board, stopTimes=board["stopTimes"][:100],
                    nextPageCursor="LATER|1788300000")
        tail = dict(board, stopTimes=board["stopTimes"][100:])
        api = _Motis(boards=[head, tail])
        with patch("src.services.hafas_service.requests.get", api):
            route = _resolve()

        assert api.paths().count("stoptimes") == 2
        second = [p for u, p in api.calls if u.endswith("/stoptimes")][1]
        assert second["pageCursor"] == "LATER|1788300000"
        assert "time" not in second
        assert route.stops[-1]["name"] == "Offenburg Bahnhof"


# ---------------------------------------------------------------------------
# precision-7 polyline decoding
# ---------------------------------------------------------------------------

class TestPrecision7Geometry:
    def test_decodes_at_the_precision_the_response_declares(self):
        leg = _fx("motis_trip_ice75.json")["legs"][0]
        assert leg["legGeometry"]["precision"] == 7

        poly = svc._decode_leg_geometry(leg)
        assert len(poly) == leg["legGeometry"]["length"] == 11385

        # Every station on the trip must sit on the decoded line. Decoding a
        # precision-7 polyline at the usual precision 5 puts it ~1000 km out, so
        # this is the assertion that actually pins the precision down.
        places = [leg["from"]] + leg["intermediateStops"] + [leg["to"]]
        for place in places:
            nearest = min(_km(place["lat"], place["lon"], p[1], p[0]) for p in poly)
            assert nearest < 0.1, f"{place['name']} is {nearest:.1f} km off the line"

    def test_decoded_points_are_lon_lat(self):
        leg = _fx("motis_trip_ice75.json")["legs"][0]
        poly = svc._decode_leg_geometry(leg)
        lon, lat = poly[0]
        assert 9.0 < lon < 11.0, "first ordinate must be longitude"
        assert 53.0 < lat < 54.0, "second ordinate must be latitude"

    def test_missing_geometry_decodes_to_nothing(self):
        assert svc._decode_leg_geometry({}) == []
        assert svc._decode_leg_geometry({"legGeometry": {"points": ""}}) == []


# ---------------------------------------------------------------------------
# Trimming the whole trip down to the user's leg
# ---------------------------------------------------------------------------

class TestGeometryTrimming:
    def test_sub_range_does_not_ship_the_whole_trip(self):
        full = svc._decode_leg_geometry(_fx("motis_trip_ice75.json")["legs"][0])
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            route = _resolve()

        assert len(route.polyline) < len(full)
        # Nothing south of Offenburg: Basel is 100 km further down the line.
        assert min(p[1] for p in route.polyline) > _BASEL_LAT + 0.5
        assert all(_km(_BASEL_LAT, _BASEL_LON, p[1], p[0]) > 50 for p in route.polyline)

    def test_reversed_segment_reverses_both_stops_and_geometry(self):
        api = _Motis(boards=[_fx("motis_stoptimes_offenburg.json")])
        with patch("src.services.hafas_service.requests.get", api):
            route = _resolve(start_lat=_OG_LAT, start_lon=_OG_LON,
                             end_lat=_HH_LAT, end_lon=_HH_LON)

        assert route.stops[0]["name"] == "Offenburg Bahnhof"
        assert route.stops[-1]["name"] == "Hamburg Hbf"
        first_lon, first_lat = route.polyline[0]
        assert _km(_OG_LAT, _OG_LON, first_lat, first_lon) < 2.0
        last_lon, last_lat = route.polyline[-1]
        assert _km(_HH_LAT, _HH_LON, last_lat, last_lon) < 2.0

    def test_trim_polyline_is_a_contiguous_slice(self):
        poly = [[float(i), 0.0] for i in range(10)]
        stops = [{"lat": 0.0, "lon": 2.0}, {"lat": 0.0, "lon": 6.0}]
        assert svc._trim_polyline(poly, stops) == [[float(i), 0.0] for i in range(2, 7)]

    def test_trim_polyline_handles_the_reversed_case(self):
        poly = [[float(i), 0.0] for i in range(10)]
        stops = [{"lat": 0.0, "lon": 6.0}, {"lat": 0.0, "lon": 2.0}]
        assert svc._trim_polyline(poly, stops) == [
            [float(i), 0.0] for i in range(6, 1, -1)]


# ---------------------------------------------------------------------------
# Train-number matching
# ---------------------------------------------------------------------------

class TestNameMatching:
    @pytest.mark.parametrize("candidate,query", [
        ("ICE 75", "ICE 75"),
        ("ICE 75", "ice 75"),
        ("ICE 75", "ICE75"),
        ("ICE 75", "75"),
        ("IC 63", "IC 63"),
        ("RJX 262", "RJX 262"),
        ("000393", "393"),          # Rejseplanen pads trip numbers
    ])
    def test_matches(self, candidate, query):
        assert svc._name_matches(candidate, query)

    @pytest.mark.parametrize("candidate,query", [
        ("ICE 755", "ICE 75"),      # the substring trap the old matcher fell into
        ("ICE 75", "ICE 755"),
        ("IC 75", "ICE 75"),
        ("ICE 75", ""),
        ("", "ICE 75"),
    ])
    def test_does_not_match(self, candidate, query):
        assert not svc._name_matches(candidate, query)

    def test_board_entry_matches_on_either_short_name(self):
        assert svc._entry_matches({"routeShortName": "ICE 75", "tripShortName": ""}, "ICE 75")
        assert svc._entry_matches({"routeShortName": "", "tripShortName": "ICE 75"}, "ICE 75")
        # Split across the two fields, as the Danish feed does.
        assert svc._entry_matches(
            {"routeShortName": "ECE", "tripShortName": "000393"}, "ECE 393")

    def test_similar_train_number_is_not_matched_off_the_board(self):
        board = _fx("motis_stoptimes_hamburg.json")
        for entry in board["stopTimes"]:
            if entry.get("tripShortName") == "ICE 75":
                entry["routeShortName"] = entry["tripShortName"] = "ICE 755"
        api = _Motis(boards=[board])
        with patch("src.services.hafas_service.requests.get", api):
            with pytest.raises(HafasError, match="not found departing"):
                _resolve()


# ---------------------------------------------------------------------------
# Country coverage — one index instead of four provider backends
# ---------------------------------------------------------------------------

class TestFinlandViaTheSameIndex:
    """Finland used to need its own rata.digitraffic.fi wire format."""

    def test_suburban_anchor_plus_radius_finds_the_long_distance_train(self):
        # Helsinki's best-scoring stop is the tram/commuter "Päärautatieasema";
        # the radius sweep is what brings the IC departures onto its board.
        api = _Motis(
            geocode=_fx("motis_reverse_geocode_helsinki.json"),
            boards=[_fx("motis_stoptimes_helsinki.json")],
        )
        with patch("src.services.hafas_service.requests.get", api):
            trip_id = svc._find_trip_id(
                svc._nearest_stop(60.172097, 24.941249)["id"], _DATE, "IC 63")

        assert trip_id
        anchor = api.params_for("/reverse-geocode")
        assert anchor["type"] == "STOP"
        assert api.params_for("/stoptimes")["radius"] == 2000


class TestAnchorSelection:
    def test_anchor_takes_the_best_scoring_stop_whatever_its_modes(self):
        """MOTIS returns only five reverse-geocode candidates and ignores a count
        parameter, so a town-centre pin can come back as five bus stops with the
        station nowhere in the list. Finding the station is the radius sweep's
        job, not a mode filter on the anchor — filtering here found nothing at
        all for Offenburg."""
        api = _Motis(boards=[_fx("motis_stoptimes_offenburg.json")])
        with patch("src.services.hafas_service.requests.get", api):
            anchor = svc._nearest_stop(_OG_LAT, _OG_LON)
            route = _resolve(start_lat=_OG_LAT, start_lon=_OG_LON,
                             end_lat=_HH_LAT, end_lon=_HH_LON)

        assert anchor["name"] == "Offenburg, Stadtkirche"
        assert not set(_fx("motis_reverse_geocode_offenburg.json")[0]["modes"]) & {
            "HIGHSPEED_RAIL", "LONG_DISTANCE", "REGIONAL_RAIL"}
        assert route.stops[0]["name"] == "Offenburg Bahnhof"

    def test_anchor_ignores_a_candidate_far_from_the_pin(self):
        api = _Motis(geocode=[{"id": "far", "name": "Far away", "lat": 0.0,
                               "lon": 0.0, "modes": ["LONG_DISTANCE"]}])
        with patch("src.services.hafas_service.requests.get", api):
            assert svc._nearest_stop(_HH_LAT, _HH_LON) is None

    def test_no_station_nearby_raises(self):
        api = _Motis(geocode=[])
        with patch("src.services.hafas_service.requests.get", api):
            with pytest.raises(HafasError, match="Could not locate a station"):
                _resolve()


# ---------------------------------------------------------------------------
# Failure handling — the contract callers depend on
# ---------------------------------------------------------------------------

class TestRetryAndErrors:
    def test_retries_a_transient_503_then_succeeds(self, _no_real_backoff):
        api = _Motis(statuses=[503, 503])
        with patch("src.services.hafas_service.requests.get", api):
            route = _resolve()

        assert route.stops[-1]["name"] == "Offenburg Bahnhof"
        # Two failed reverse-geocode attempts, then the real three calls.
        assert api.paths() == ["reverse-geocode"] * 3 + ["stoptimes", "trip"]
        assert [c.args[0] for c in _no_real_backoff.call_args_list] == [1.0, 2.0]

    def test_exhausted_retries_raise_the_error_callers_catch(self):
        api = _Motis(statuses=[503, 503, 503])
        with patch("src.services.hafas_service.requests.get", api):
            with pytest.raises(HafasError, match="unavailable after 3 attempts"):
                _resolve()
        assert api.paths() == ["reverse-geocode"] * 3

    def test_rate_limiting_is_retried_too(self):
        api = _Motis(statuses=[429])
        with patch("src.services.hafas_service.requests.get", api):
            assert _resolve().stops[-1]["name"] == "Offenburg Bahnhof"

    def test_a_4xx_is_not_retried(self):
        api = _Motis(statuses=[404])
        with patch("src.services.hafas_service.requests.get", api):
            with pytest.raises(HafasError, match="Train route lookup failed"):
                _resolve()
        assert api.paths() == ["reverse-geocode"]

    def test_non_json_body_raises_hafas_error(self):
        """The Rejseplanen trap: an HTTP 299 HTML page that .json() chokes on."""
        class _Html(_Resp):
            def json(self):
                raise ValueError("Expecting value: line 1 column 1 (char 0)")

        with patch("src.services.hafas_service.requests.get",
                   lambda *a, **k: _Html(None, 299)):
            with pytest.raises(HafasError, match="Train route lookup failed"):
                _resolve()

    def test_train_that_does_not_serve_the_destination_is_rejected(self):
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            with pytest.raises(HafasError, match="does not stop near the end"):
                _resolve(end_lat=41.9028, end_lon=12.4964)   # Rome

    def test_missing_date_raises_without_calling_the_api(self):
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            with pytest.raises(HafasError, match="No usable service date"):
                _resolve(date="")
        assert api.calls == []

    def test_outbound_calls_are_counted(self, metric):
        before = metric("viewtrip_external_requests_total",
                        service="hafas", endpoint="motis/trip", outcome="success")
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            _resolve()
        after = metric("viewtrip_external_requests_total",
                       service="hafas", endpoint="motis/trip", outcome="success")
        assert after - before == 1


class TestReverseGeocodeCache:
    def test_same_endpoint_is_geocoded_once(self):
        api = _Motis()
        with patch("src.services.hafas_service.requests.get", api):
            _resolve()
            _resolve()
        assert api.paths().count("reverse-geocode") == 1
