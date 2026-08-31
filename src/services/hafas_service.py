"""Train schedule + track geometry, resolved through MOTIS (Transitous).

Turns a train number and a service date into an ordered list of stops **and**
the real track polyline of that journey, using the public MOTIS instance at
https://api.transitous.org.

Why this replaced the four HAFAS provider backends
--------------------------------------------------
Every bespoke backend this module used to carry is dead or not worth a second
code path (verified against the live endpoints, issue #277):

* ``db``  — ``v6.db.transport.rest`` answers **503** on every API path. DB
  switched its HAFAS endpoint off permanently; the wrapper now proxies
  ``db-vendo-client``, which has a ~60 req/min quota and, per its own readme,
  "haphazard blocking".
* ``obb`` — ``oebb.macistry.com`` answers 503 "This service has been suspended
  by its owner."
* ``dsb`` — ``xmlopen.rejseplanen.dk`` answers HTTP **299** with an HTML page
  saying API 1.0 is closed. 299 is a 2xx, so ``raise_for_status()`` never
  fired and the old code called ``.json()`` on HTML.
* ``vr``  — ``rata.digitraffic.fi`` is healthy, but the same Finnish data
  (``fi-digitraffic``) is in the Transitous index, so it no longer earns its
  own wire format.

Both ``db-rest`` and ``db-vendo-client`` now point users at Transitous as the
migration path, and one MOTIS index covers DE/AT/DK/FI in a single API. The
``hafas_provider`` field is therefore vestigial: stored segments still carry it
and it is still persisted, but resolution ignores it.

Two defects disappear with the move:

1. **Match on a departure board, not a journey planner.** The old lookup asked
   ``/journeys`` for 15 results from a hardcoded 06:00+01:00 and passed
   ``lineName=<train>`` — a parameter ``hafas-rest-api``'s journeys route does
   not have, so it was silently ignored and the code just scanned 15 arbitrary
   journeys. ICE 75 leaves Hamburg Hbf at 14:29 local with 275 rail departures
   ahead of it on the board: it could never be found. ``/stoptimes`` is indexed
   by stop and time, so a train-number lookup is an exact scan of the service
   day instead of a 15-result guess.
2. **``/trip`` returns ``legGeometry``** — the whole journey's real track as an
   encoded polyline — so a matched train needs no Overpass query at all. That
   removes the bounding-box query cascade (3 mirrors x 45 s) from the train
   path entirely. ``overpass_service.get_rail_geometry`` remains the fallback
   for segments with no train number, or whose train could not be matched.

Raises HafasError on any failure — callers fall back to coordinate-only mode.
"""
from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Any, Optional

import polyline as polyline_lib
import requests

from src.utils.logging import get_logger
from src.utils.metrics import track_external

_log = get_logger(__name__)

_MOTIS_BASE = "https://api.transitous.org/api/v1"

# Transitous asks API users to identify themselves and keep volume modest
# (https://transitous.org/api/). Same format as overpass_service._HEADERS.
_HEADERS = {
    "User-Agent": "ViewTripWeb/1.0 (https://github.com/viewtrip; train route resolver)"
}

_TIMEOUT = 20  # seconds per request

# A resolve makes at most three MOTIS calls: one reverse-geocode, one or two
# departure-board pages, one trip. Retry only on the statuses that mean "try
# again later" — a single 503 used to end the whole resolve.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
_BACKOFF_S = 1.0  # 1 s then 2 s; bounded so the client's poll window survives it

# Rail modes accepted for the departure board. Regional services are included
# because users do enter regional train numbers; the extra volume costs nothing
# in requests (measured: one 500-entry page spans ~23 h at Hamburg Hbf).
_BOARD_MODES = (
    "HIGHSPEED_RAIL,LONG_DISTANCE,NIGHT_RAIL,REGIONAL_FAST_RAIL,REGIONAL_RAIL"
)

# Merge every stop within this radius of the anchor into one board. This is
# what makes a single reverse-geocode hit good enough as an anchor: MOTIS
# returns only five candidates and does not honour a count parameter, so a pin
# dropped on a town centre can come back as five bus stops with the station
# nowhere in the list (verified at Offenburg). Anchoring on the best-scoring
# stop whatever its modes, and sweeping 2 km around it, puts the station's rail
# departures on the board anyway — verified from an Offenburg bus stop and from
# a Hamburg U-Bahn platform, both of which then see ICE 75. The board is
# already filtered to rail modes, so the wider radius costs nothing.
_STOP_RADIUS_M = 2000

_BOARD_PAGE_SIZE = 500
_BOARD_MAX_PAGES = 4  # hard stop; one page already spans ~23 h at Hamburg Hbf

# How far a trip's nearest stop may be from the segment endpoint the user
# placed. Generous — pins get dropped on city centres, not platforms — but
# tight enough that a train not actually serving the endpoint is rejected
# instead of silently producing a plausible-looking wrong route.
_MAX_ENDPOINT_SNAP_KM = 30.0

# The stop's timezone isn't known before the first request and DE/AT/DK/FI all
# sit at UTC+1…+3, so the service-day window is a fixed UTC span rather than a
# tz-database lookup: start 3 h before 00:00 UTC (local midnight at UTC+3,
# earlier elsewhere) through 00:00 UTC the next day (01:00-03:00 local). A train
# number repeats daily on the same path, so over-reaching at the edges cannot
# select a wrong *route*.
_DAY_START_SLACK = timedelta(hours=3)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class HafasError(Exception):
    pass


@dataclass
class TrainRoute:
    """A matched train service, trimmed to the caller's own two endpoints.

    ``polyline`` is the real track as ``[[lon, lat], …]`` — the same coordinate
    order ``overpass_service`` uses. It is empty when MOTIS returned a trip with
    no geometry, which tells the caller to fall back to Overpass.
    """
    stops: list[dict]            # [{name, lat, lon, uic}, …] start → end
    polyline: list[list[float]]  # [[lon, lat], …] start → end, or []


def get_train_route(
    train_number: str,
    date: str,          # ISO "YYYY-MM-DD"
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> TrainRoute:
    """Resolve *train_number* on *date* into its stops and real track geometry.

    Raises HafasError if the train can't be matched, doesn't serve the given
    endpoints, or the API fails.
    """
    name = re.sub(r"\s+", " ", (train_number or "").strip())
    if not name:
        raise HafasError("No train number given")
    if not _DATE_RE.match(date or ""):
        _log.warning("train lookup failed: no usable service date (train=%r date=%r)",
                     name, date)
        raise HafasError(f"No usable service date for train {name!r}")

    try:
        anchor = _nearest_stop(start_lat, start_lon)
        if anchor is None:
            _log.warning(
                "train lookup failed: no stop near the start point "
                "(train=%r start=%s,%s)", name, start_lat, start_lon)
            raise HafasError("Could not locate a station near the start point")

        trip_id = _find_trip_id(anchor["id"], date, name)
        if not trip_id:
            _log.warning(
                "train lookup failed: %r not on the %s departure board at %s",
                name, date, anchor["name"])
            raise HafasError(
                f"Train {name!r} not found departing {anchor['name']} on {date}")

        stops, poly = _trip_stops_and_geometry(trip_id)
        if len(stops) < 2:
            _log.warning("train lookup failed: trip %r returned fewer than 2 stops", name)
            raise HafasError("Trip returned fewer than 2 stops")

        trimmed = _trim_stops(stops, start_lat, start_lon, end_lat, end_lon)
        if len(trimmed) < 2:
            _log.warning(
                "train lookup failed: %r start and end snap to the same stop", name)
            raise HafasError(
                f"Train {name!r} serves only one of this segment's endpoints")
        _check_serves_endpoints(trimmed, name, start_lat, start_lon, end_lat, end_lon)

        return TrainRoute(trimmed, _trim_polyline(poly, trimmed))

    except HafasError:
        raise
    except Exception as exc:
        _log.exception(
            "train route lookup failed unexpectedly (train=%r date=%s start=%s,%s end=%s,%s)",
            name, date, start_lat, start_lon, end_lat, end_lon)
        raise HafasError(f"Train route lookup failed: {exc}") from exc


# ---------------------------------------------------------------------------
# MOTIS transport
# ---------------------------------------------------------------------------

def _get(path: str, params: dict) -> Any:
    """GET a MOTIS endpoint, retrying transient 5xx/429 with backoff.

    A single 503 used to end a resolve outright. Attempts are capped at three
    with 1 s/2 s backoff so the worst case stays well inside the client's poll
    window.
    """
    url = f"{_MOTIS_BASE}{path}"
    endpoint = f"motis{path}"
    last = ""
    for attempt in range(_MAX_ATTEMPTS):
        with track_external("hafas", endpoint) as call:
            resp = requests.get(url, params=params, headers=_HEADERS, timeout=_TIMEOUT)
            if resp.status_code in _RETRY_STATUS:
                call.outcome = "retryable_error"
                last = f"HTTP {resp.status_code}"
            else:
                resp.raise_for_status()
                return resp.json()
        if attempt < _MAX_ATTEMPTS - 1:
            time.sleep(_BACKOFF_S * (2 ** attempt))
    raise HafasError(f"MOTIS {path} unavailable after {_MAX_ATTEMPTS} attempts: {last}")


def _nearest_stop(lat: float, lon: float) -> Optional[dict]:
    """Board anchor for (lat, lon) — the nearest MOTIS stop, or None."""
    # Round before caching: 4 dp is ~11 m, so repeated resolves of segments
    # sharing a station reuse one reverse-geocode instead of one each.
    found = _nearest_stop_cached(round(lat, 4), round(lon, 4))
    return {"id": found[0], "name": found[1]} if found else None


@lru_cache(maxsize=256)
def _nearest_stop_cached(lat: float, lon: float) -> Optional[tuple[str, str]]:
    """(id, name) of the anchor stop, cached. Returns a tuple so the cached
    value can't be mutated by a caller."""
    results = _get("/reverse-geocode", {"place": f"{lat},{lon}", "type": "STOP"})
    if not isinstance(results, list):
        return None
    # Results come back best-first (MOTIS scores distance against importance).
    # Mode isn't a filter here — see _STOP_RADIUS_M.
    for r in results:
        if r.get("lat") is None or r.get("lon") is None:
            continue
        if _crow_km(lat, lon, r["lat"], r["lon"]) > _MAX_ENDPOINT_SNAP_KM:
            continue
        return str(r["id"]), str(r.get("name", ""))
    return None


def _find_trip_id(stop_id: str, date: str, train_name: str) -> Optional[str]:
    """First trip on *stop_id*'s board within *date*'s service day matching *train_name*.

    Pages forward with MOTIS's own ``pageCursor`` instead of brute-forcing a
    huge ``n``: one 500-entry page already spans ~23 h of the 27 h window at
    Germany's busiest station, so this is normally a single request.
    """
    start, end = _service_window(date)
    cursor: Optional[str] = None

    for _page in range(_BOARD_MAX_PAGES):
        params: dict[str, Any] = {
            "stopId": stop_id,
            "n": _BOARD_PAGE_SIZE,
            "radius": _STOP_RADIUS_M,
            "mode": _BOARD_MODES,
        }
        if cursor:
            params["pageCursor"] = cursor
        else:
            params["time"] = _iso_z(start)

        data = _get("/stoptimes", params)
        entries = data.get("stopTimes") or []
        if not entries:
            return None

        for entry in entries:
            when = _entry_time(entry)
            if when is not None and when >= end:
                return None  # past the service day — the train isn't running today
            if when is not None and when < start:
                continue
            if _entry_matches(entry, train_name):
                trip_id = entry.get("tripId")
                if trip_id:
                    return trip_id

        last = _entry_time(entries[-1])
        if last is not None and last >= end:
            return None
        cursor = data.get("nextPageCursor")
        if not cursor:
            return None
    return None


def _trip_stops_and_geometry(trip_id: str) -> tuple[list[dict], list[list[float]]]:
    """Whole-trip stop list and decoded track for a MOTIS trip id."""
    data = _get("/trip", {"tripId": trip_id})
    stops: list[dict] = []
    poly: list[list[float]] = []

    for leg in data.get("legs") or []:
        places = [leg.get("from")] + list(leg.get("intermediateStops") or []) + [leg.get("to")]
        for place in places:
            stop = _stop_from_place(place)
            if stop is None:
                continue
            if stops and (stop["lat"], stop["lon"]) == (stops[-1]["lat"], stops[-1]["lon"]):
                continue  # a through-leg boundary repeats the shared stop
            stops.append(stop)

        part = _decode_leg_geometry(leg)
        if poly and part and part[0] == poly[-1]:
            part = part[1:]
        poly.extend(part)

    return stops, poly


def _stop_from_place(place: Optional[dict]) -> Optional[dict]:
    if not place or place.get("lat") is None or place.get("lon") is None:
        return None
    return {
        "name": place.get("name", ""),
        "lat": place["lat"],
        "lon": place["lon"],
        # MOTIS stop IDs are feed-scoped (``de-DELFI_de:02000:10950``), not UIC
        # codes; overpass_service only accepts numeric UIC refs, so leave it
        # empty and let its own enrichment run if it is ever needed.
        "uic": "",
    }


def _decode_leg_geometry(leg: dict) -> list[list[float]]:
    """Decode ``legGeometry`` into ``[[lon, lat], …]``.

    MOTIS encodes at **precision 7**, ten times the usual Google-polyline
    precision — decoding at the default 5 would place the line ~1000 km away.
    The response states its own precision, so honour that rather than assume.
    """
    geometry = leg.get("legGeometry") or {}
    encoded = geometry.get("points")
    if not encoded:
        return []
    precision = int(geometry.get("precision") or 5)
    return [[lon, lat] for lat, lon in polyline_lib.decode(encoded, precision=precision)]


# ---------------------------------------------------------------------------
# Matching and trimming
# ---------------------------------------------------------------------------

def _service_window(date: str) -> tuple[datetime, datetime]:
    """UTC window covering the whole local service day of *date*. See _DAY_START_SLACK."""
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    return day - _DAY_START_SLACK, day + timedelta(days=1)


def _iso_z(when: datetime) -> str:
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _entry_time(entry: dict) -> Optional[datetime]:
    place = entry.get("place") or {}
    raw = place.get("departure") or place.get("arrival")
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _entry_matches(entry: dict, train_name: str) -> bool:
    route = entry.get("routeShortName") or ""
    trip = entry.get("tripShortName") or ""
    # Most feeds set both to the full name ("ICE 75"); some split them
    # ("ECE" + "000393"), so the concatenation is a candidate too.
    return any(_name_matches(c, train_name)
               for c in (trip, route, f"{route} {trip}") if c.strip())


_NON_ALNUM_RE = re.compile(r"[^A-Z0-9]")


def _name_matches(line_name: str, query: str) -> bool:
    """True if *line_name* names the service the user asked for.

    Compares the letter part and the number part separately, which is stricter
    than the substring test this replaced: "ICE 75" no longer matches "ICE 755"
    (a real hazard now that whole departure boards are scanned). A bare number
    still matches a named service, and leading zeros are ignored so "393"
    matches Rejseplanen's "000393".
    """
    a_letters, a_digits = _split_name(line_name)
    b_letters, b_digits = _split_name(query)
    if not (a_letters or a_digits) or not (b_letters or b_digits):
        return False
    if a_digits.lstrip("0") != b_digits.lstrip("0"):
        return False
    return not b_letters or not a_letters or a_letters == b_letters


def _split_name(name: str) -> tuple[str, str]:
    norm = _NON_ALNUM_RE.sub("", (name or "").upper())
    return re.sub(r"\d", "", norm), re.sub(r"\D", "", norm)


def _check_serves_endpoints(
    stops: list[dict],
    train_name: str,
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> None:
    """Reject a match whose stops are nowhere near the segment's endpoints.

    The board is searched from the start stop only, so nothing else guarantees
    the matched train also serves the destination. Without this a wrong match
    would silently yield a confident-looking but wrong line.
    """
    for stop, (lat, lon), which in (
        (stops[0], (lat1, lon1), "start"),
        (stops[-1], (lat2, lon2), "end"),
    ):
        gap = _crow_km(lat, lon, stop["lat"], stop["lon"])
        if gap > _MAX_ENDPOINT_SNAP_KM:
            _log.warning(
                "train lookup failed: %r does not serve the %s point "
                "(nearest stop %r is %.0f km away)", train_name, which, stop["name"], gap)
            raise HafasError(
                f"Train {train_name!r} does not stop near the {which} of this segment")


def _trim_stops(
    stops: list[dict],
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> list[dict]:
    def d2(s, lat, lon):
        return (s["lat"] - lat) ** 2 + (s["lon"] - lon) ** 2

    si = min(range(len(stops)), key=lambda i: d2(stops[i], lat1, lon1))
    ei = min(range(len(stops)), key=lambda i: d2(stops[i], lat2, lon2))

    if si <= ei:
        return stops[si : ei + 1]
    return list(reversed(stops[ei : si + 1]))


def _trim_polyline(poly: list[list[float]], stops: list[dict]) -> list[list[float]]:
    """Cut the whole-trip track down to the caller's own two endpoints.

    ``/trip`` returns the entire service — Hamburg→Basel for a Hamburg→Offenburg
    segment — so the geometry needs the same treatment ``_trim_stops`` gives the
    stop list, including the reversal when the segment runs against the trip's
    direction of travel.
    """
    if len(poly) < 2 or len(stops) < 2:
        return []
    i = _nearest_point(poly, stops[0])
    j = _nearest_point(poly, stops[-1])
    part = poly[i : j + 1] if i <= j else list(reversed(poly[j : i + 1]))
    return part if len(part) >= 2 else []


def _nearest_point(poly: list[list[float]], stop: dict) -> int:
    lat, lon = stop["lat"], stop["lon"]
    return min(
        range(len(poly)),
        key=lambda k: (poly[k][1] - lat) ** 2 + (poly[k][0] - lon) ** 2,
    )


def _crow_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance in km (equirectangular; same approx as overpass_service)."""
    dlat = (lat1 - lat2) * 111.0
    dlon = (lon1 - lon2) * 111.0 * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot(dlat, dlon)
