"""
HAFAS-based train schedule service.

Queries public transport REST APIs (Deutsche Bahn, ÖBB, others via
transport.rest mirror) to resolve a train number into an ordered sequence
of stops with coordinates.

DSB (Denmark) uses the Rejseplanen legacy HAFAS XML-Open API, which has a
different wire format from transport.rest.

Raises HafasError on any failure — callers fall back to coordinate-only mode.
"""
from __future__ import annotations

import re
from typing import Optional

import requests

# transport.rest mirrors for supported providers
_ENDPOINTS: dict[str, str] = {
    "db":  "https://v6.db.transport.rest",
    "obb": "https://oebb.macistry.com/api",
}

# Rejseplanen legacy HAFAS XML-Open API (DSB / Denmark)
_REJSEPLANEN_BASE = "https://xmlopen.rejseplanen.dk/bin/rest.exe"

_TIMEOUT = 12  # seconds per request


class HafasError(Exception):
    pass


def get_stop_sequence(
    provider: str,
    train_number: str,
    date: str,          # ISO "YYYY-MM-DD"
    start_lat: float,
    start_lon: float,
    end_lat: float,
    end_lon: float,
) -> list[dict]:
    """
    Return an ordered list of stops [{name, lat, lon, uic}, …] start→end.
    Raises HafasError if provider unsupported, train not found, or network fails.
    """
    p = provider.lower()
    if p == "dsb":
        return _rp_get_stop_sequence(
            train_number, date, start_lat, start_lon, end_lat, end_lon
        )

    base = _ENDPOINTS.get(p)
    if not base:
        raise HafasError(f"Unsupported HAFAS provider: {provider!r}")

    train_name = re.sub(r"\s+", " ", train_number.strip())

    try:
        start_stop = _nearest_stop(base, start_lat, start_lon)
        end_stop   = _nearest_stop(base, end_lat, end_lon)
        if not start_stop or not end_stop:
            raise HafasError("Could not locate nearby stops")

        trip_id = _find_trip_id(base, start_stop["id"], end_stop["id"], date, train_name)
        if not trip_id:
            raise HafasError(
                f"Train {train_name!r} not found in journeys "
                f"{start_stop['name']} → {end_stop['name']}"
            )

        stops = _trip_stops(base, trip_id)
        if len(stops) < 2:
            raise HafasError("Trip returned fewer than 2 stops")

        return _trim_stops(stops, start_lat, start_lon, end_lat, end_lon)

    except HafasError:
        raise
    except Exception as exc:
        raise HafasError(f"HAFAS request failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Rejseplanen (DSB / Denmark) — legacy HAFAS XML-Open API
# Wire format differs from transport.rest: HAFAS integer coords (×1 000 000),
# DD.MM.YYYY dates, TripList/JourneyDetail JSON structure.
# ---------------------------------------------------------------------------

def _rp_get_stop_sequence(
    train_number: str,
    date: str,
    start_lat: float, start_lon: float,
    end_lat: float, end_lon: float,
) -> list[dict]:
    train_name = re.sub(r"\s+", " ", train_number.strip())
    try:
        start_stop = _rp_nearest_stop(start_lat, start_lon)
        end_stop   = _rp_nearest_stop(end_lat, end_lon)
        if not start_stop or not end_stop:
            raise HafasError("Could not locate nearby stops via Rejseplanen")

        ref = _rp_find_trip_ref(start_stop["id"], end_stop["id"], date, train_name)
        if not ref:
            raise HafasError(
                f"Train {train_name!r} not found "
                f"{start_stop['name']} → {end_stop['name']} via Rejseplanen"
            )

        stops = _rp_trip_stops(ref)
        if len(stops) < 2:
            raise HafasError("Rejseplanen trip returned fewer than 2 stops")

        return _trim_stops(stops, start_lat, start_lon, end_lat, end_lon)
    except HafasError:
        raise
    except Exception as exc:
        raise HafasError(f"Rejseplanen request failed: {exc}") from exc


def _rp_nearest_stop(lat: float, lon: float) -> Optional[dict]:
    resp = requests.get(
        f"{_REJSEPLANEN_BASE}/location.nearbystops",
        params={
            "coordX": int(lon * 1_000_000),
            "coordY": int(lat * 1_000_000),
            "maxNo": 1,
            "format": "json",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    locs = (data.get("LocationList") or {}).get("StopLocation") or []
    if isinstance(locs, dict):
        locs = [locs]
    if not locs:
        return None
    s = locs[0]
    return {
        "id": str(s.get("id", "")),
        "name": s.get("name", ""),
        "lat": int(s["y"]) / 1_000_000,
        "lon": int(s["x"]) / 1_000_000,
    }


def _rp_find_trip_ref(
    from_id: str, to_id: str, date: str, train_name: str
) -> Optional[str]:
    rp_date = f"{date[8:10]}.{date[5:7]}.{date[0:4]}"
    resp = requests.get(
        f"{_REJSEPLANEN_BASE}/trip",
        params={
            "originId": from_id,
            "destId": to_id,
            "date": rp_date,
            "time": "06:00",
            "format": "json",
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    trips = (data.get("TripList") or {}).get("Trip") or []
    if isinstance(trips, dict):
        trips = [trips]
    for trip in trips:
        legs = trip.get("Leg") or []
        if isinstance(legs, dict):
            legs = [legs]
        for leg in legs:
            if _name_matches(leg.get("name", ""), train_name):
                ref = (leg.get("JourneyDetailRef") or {}).get("ref", "")
                if ref:
                    return ref
    return None


def _rp_trip_stops(ref: str) -> list[dict]:
    url = ref if ref.startswith("http") else f"{_REJSEPLANEN_BASE}{ref}"
    if "format=json" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}format=json"
    resp = requests.get(url, timeout=_TIMEOUT)
    resp.raise_for_status()
    raw = (resp.json().get("JourneyDetail") or {}).get("Stop") or []
    if isinstance(raw, dict):
        raw = [raw]
    stops = []
    for s in raw:
        x = s.get("x")
        y = s.get("y")
        if x is None or y is None:
            continue
        stops.append({
            "name": s.get("name", ""),
            "lat": int(y) / 1_000_000,
            "lon": int(x) / 1_000_000,
            "uic": str(s.get("id", "")),
        })
    return stops


# ---------------------------------------------------------------------------
# transport.rest helpers (DB, ÖBB, …)
# ---------------------------------------------------------------------------

def _nearest_stop(base: str, lat: float, lon: float) -> Optional[dict]:
    resp = requests.get(
        f"{base}/stops/nearby",
        params={"latitude": lat, "longitude": lon, "results": 1, "distance": 3000},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    stops = resp.json()
    return stops[0] if stops else None


def _find_trip_id(
    base: str, from_id: str, to_id: str, date: str, train_name: str
) -> Optional[str]:
    resp = requests.get(
        f"{base}/journeys",
        params={
            "from": from_id,
            "to": to_id,
            "departure": f"{date}T06:00:00+01:00",
            "results": 15,
            "stopovers": "false",
            "lineName": train_name,
        },
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    for journey in (resp.json().get("journeys") or []):
        for leg in (journey.get("legs") or []):
            line = (leg.get("line") or {})
            if _name_matches(line.get("name", ""), train_name):
                tid = leg.get("tripId")
                if tid:
                    return tid
    return None


def _trip_stops(base: str, trip_id: str) -> list[dict]:
    encoded = requests.utils.quote(trip_id, safe="")
    resp = requests.get(
        f"{base}/trips/{encoded}",
        params={"stopovers": "true"},
        timeout=_TIMEOUT,
    )
    resp.raise_for_status()
    stops = []
    for so in (resp.json().get("stopovers") or []):
        stop = so.get("stop") or {}
        loc  = stop.get("location") or {}
        lat  = loc.get("latitude")
        lon  = loc.get("longitude")
        if lat is None or lon is None:
            continue
        stops.append({
            "name": stop.get("name", ""),
            "lat":  lat,
            "lon":  lon,
            "uic":  stop.get("id", ""),
        })
    return stops


def _name_matches(line_name: str, query: str) -> bool:
    a = re.sub(r"\s+", "", line_name.upper())
    b = re.sub(r"\s+", "", query.upper())
    return a == b or b in a or a in b


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
