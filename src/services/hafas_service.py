"""
HAFAS-based train schedule service.

Queries public transport REST APIs (Deutsche Bahn, ÖBB, others via
transport.rest mirror) to resolve a train number into an ordered sequence
of stops with coordinates.

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
    base = _ENDPOINTS.get(provider.lower())
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
# Helpers
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
