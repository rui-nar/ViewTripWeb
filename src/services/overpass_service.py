"""
Overpass API service — extracts railway geometry from OpenStreetMap.

Two strategies (tried in order):
  3a  Route-relation strategy: query OSM train route relations containing
      both station nodes (matched by uic_ref tag).  Returns the ordered
      way geometry directly.
  3b  Coordinate fallback: query railway ways inside the bounding box,
      build a node graph, and route with Dijkstra between the two nearest
      nodes to start/end coords.
"""
from __future__ import annotations

import heapq
import json
import math
import re
from typing import Optional

import requests

# ÖBB and some HAFAS providers return compound location IDs like
# "A=1@O=Linz Hbf@X=14280@Y=48290@U=81@L=8100013@…"
# Extract the numeric station code from the @L= field.
_HAFAS_L_RE = re.compile(r'@L=(\d+)@')

_OVERPASS_URL = "https://overpass-api.de/api/interpreter"
_TIMEOUT_QUERY = 30   # seconds for the Overpass QL timeout directive
_TIMEOUT_HTTP  = 45   # HTTP socket timeout


class OverpassError(Exception):
    pass


def get_rail_geometry(stops: list[dict]) -> list[list[float]]:
    """
    Return [[lon, lat], …] polyline from stops[0] to stops[-1].

    *stops* is a list of dicts with keys lat, lon, and optionally uic.
    Route-relation strategy is tried first (requires UIC codes — discovered
    from OSM if not already present). Falls back to coordinate Dijkstra.
    """
    if len(stops) < 2:
        raise OverpassError("Need at least 2 stops")

    # Enrich stops with UIC codes from OSM if not already present
    enriched = [_enrich_uic(s) for s in stops]

    if all(s.get("uic") for s in enriched):
        try:
            return _via_route_relations(enriched)
        except OverpassError:
            pass  # fall through to coordinate fallback

    return _via_coordinate_fallback(enriched)


def _enrich_uic(stop: dict) -> dict:
    """Return stop with a valid numeric uic_ref, snapping lat/lon to the OSM station if needed."""
    raw = stop.get("uic", "")

    # Already a bare numeric UIC — nothing to do.
    if raw and raw.isdigit():
        return stop

    # HAFAS compound ID (e.g. ÖBB "A=1@O=...@L=8100013@...") — extract the code.
    if raw and "@" in raw:
        m = _HAFAS_L_RE.search(raw)
        if m:
            return {**stop, "uic": m.group(1)}

    # Missing or unrecognised format — look up the nearest OSM station and also
    # snap lat/lon to that station so the Dijkstra starts on the actual mainline.
    station = _find_station_near(stop["lat"], stop["lon"])
    if station:
        return {**stop, "uic": station["uic"], "lat": station["lat"], "lon": station["lon"]}
    return {**stop, "uic": ""}


def _find_station_near(lat: float, lon: float, radius_m: int = 2000) -> Optional[dict]:
    """
    Nearest OSM railway station within radius_m metres.
    Returns {lat, lon, uic} or None.
    """
    query = f"""
[out:json][timeout:15];
node["railway"~"^(station|halt)$"]["uic_ref"](around:{radius_m},{lat},{lon});
out body;
"""
    try:
        data = _overpass(query)
        elements = data.get("elements", [])
        if not elements:
            return None
        nearest = min(
            elements,
            key=lambda e: (e.get("lat", 0) - lat) ** 2 + (e.get("lon", 0) - lon) ** 2,
        )
        uic = nearest.get("tags", {}).get("uic_ref")
        if not uic:
            return None
        return {"lat": nearest["lat"], "lon": nearest["lon"], "uic": uic}
    except OverpassError:
        return None


def _find_uic_near(lat: float, lon: float, radius_m: int = 2000) -> Optional[str]:
    """Return the uic_ref of the nearest OSM railway station, or None."""
    result = _find_station_near(lat, lon, radius_m)
    return result["uic"] if result else None


# ---------------------------------------------------------------------------
# Strategy 3a — route relations
# ---------------------------------------------------------------------------

def _via_route_relations(stops: list[dict]) -> list[list[float]]:
    full: list[list[float]] = []
    for i in range(len(stops) - 1):
        seg = _route_relation_segment(stops[i], stops[i + 1])
        if seg is None:
            raise OverpassError("No route relation covers a stop pair")
        full = full + (seg[1:] if full else seg)
    if len(full) < 2:
        raise OverpassError("Route-relation strategy returned empty geometry")
    return full


def _route_relation_segment(s1: dict, s2: dict) -> Optional[list[list[float]]]:
    uic1 = _clean_uic(s1["uic"])
    uic2 = _clean_uic(s2["uic"])

    query = f"""
[out:json][timeout:{_TIMEOUT_QUERY}];
node["uic_ref"="{uic1}"]->.a;
node["uic_ref"="{uic2}"]->.b;
(
  rel["route"="train"](bn.a)(bn.b);
  rel["route"="railway"](bn.a)(bn.b);
  rel["route"="light_rail"](bn.a)(bn.b);
)->.r;
.r out geom;
"""
    data = _overpass(query)
    elements = data.get("elements", [])
    if not elements:
        return None
    return _extract_geometry(elements[0], s1["lat"], s1["lon"], s2["lat"], s2["lon"])


def _clean_uic(uic: str) -> str:
    return uic.lstrip("0") or uic


def _extract_geometry(
    rel: dict,
    lat1: float, lon1: float, lat2: float, lon2: float,
) -> Optional[list[list[float]]]:
    segments: list[list[list[float]]] = []
    for m in rel.get("members", []):
        if m.get("type") != "way":
            continue
        geom = m.get("geometry", [])
        if len(geom) < 2:
            continue
        segments.append([[pt["lon"], pt["lat"]] for pt in geom])

    if not segments:
        return None

    polyline = _chain(segments)
    return _trim(polyline, lat1, lon1, lat2, lon2) if len(polyline) >= 2 else None


def _chain(segs: list[list[list[float]]]) -> list[list[float]]:
    result = list(segs[0])
    for seg in segs[1:]:
        if not seg:
            continue
        if _sq(result[-1], seg[-1]) < _sq(result[-1], seg[0]):
            seg = list(reversed(seg))
        result += seg[1:] if _sq(result[-1], seg[0]) < 1e-12 else seg
    return result


def _trim(
    poly: list[list[float]],
    lat1: float, lon1: float, lat2: float, lon2: float,
) -> list[list[float]]:
    si = min(range(len(poly)), key=lambda i: _sq(poly[i], [lon1, lat1]))
    ei = min(range(len(poly)), key=lambda i: _sq(poly[i], [lon2, lat2]))
    if si <= ei:
        return poly[si : ei + 1]
    return list(reversed(poly[ei : si + 1]))


# ---------------------------------------------------------------------------
# Strategy 3b — coordinate fallback (bounding-box Dijkstra)
# ---------------------------------------------------------------------------

def _via_coordinate_fallback(stops: list[dict]) -> list[list[float]]:
    full: list[list[float]] = []
    for i in range(len(stops) - 1):
        seg = _coord_segment(
            stops[i]["lat"], stops[i]["lon"],
            stops[i + 1]["lat"], stops[i + 1]["lon"],
        )
        full = full + (seg[1:] if full else seg)
    return full if len(full) >= 2 else _straight(
        stops[0]["lat"], stops[0]["lon"], stops[-1]["lat"], stops[-1]["lon"]
    )


def _coord_segment(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> list[list[float]]:
    buf = 0.25
    bbox = (
        min(lat1, lat2) - buf, min(lon1, lon2) - buf,
        max(lat1, lat2) + buf, max(lon1, lon2) + buf,
    )
    # No usage filter — OSM tagging conventions vary by country (Germany uses
    # usage=main/branch; France often uses usage=main_line or omits it entirely).
    # The railway type filter is restrictive enough to avoid excessive data.
    query = (
        f"[out:json][timeout:{_TIMEOUT_QUERY}];"
        f'way["railway"~"^(rail|narrow_gauge|light_rail)$"]'
        f'["service"!~"."]'
        f"({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});"
        "out geom;"
    )
    try:
        data = _overpass(query)
    except OverpassError:
        return _straight(lat1, lon1, lat2, lon2)

    ways = data.get("elements", [])
    if not ways:
        return _straight(lat1, lon1, lat2, lon2)

    # Build adjacency graph
    nodes: dict[str, list[float]] = {}
    adj:   dict[str, list[str]]   = {}
    for way in ways:
        prev: Optional[str] = None
        for pt in way.get("geometry", []):
            nid = f"{pt['lat']:.6f},{pt['lon']:.6f}"
            nodes[nid] = [pt["lon"], pt["lat"]]
            if prev is not None:
                adj.setdefault(prev, []).append(nid)
                adj.setdefault(nid,  []).append(prev)
            prev = nid

    if not nodes:
        return _straight(lat1, lon1, lat2, lon2)

    start_node = _nearest_node(nodes, lat1, lon1)
    end_node   = _nearest_node(nodes, lat2, lon2)
    path = _dijkstra(nodes, adj, start_node, end_node)

    if path:
        return [[lon1, lat1]] + [nodes[n] for n in path] + [[lon2, lat2]]
    return _straight(lat1, lon1, lat2, lon2)


def _nearest_node(nodes: dict[str, list[float]], lat: float, lon: float) -> str:
    return min(nodes, key=lambda n: (nodes[n][1] - lat) ** 2 + (nodes[n][0] - lon) ** 2)


def _dijkstra(
    nodes: dict[str, list[float]],
    adj: dict[str, list[str]],
    start: str,
    end: str,
) -> Optional[list[str]]:
    dist: dict[str, float] = {start: 0.0}
    prev: dict[str, Optional[str]] = {start: None}
    heap = [(0.0, start)]
    visited: set[str] = set()

    while heap:
        d, u = heapq.heappop(heap)
        if u in visited:
            continue
        visited.add(u)
        if u == end:
            path: list[str] = []
            cur: Optional[str] = end
            while cur is not None:
                path.append(cur)
                cur = prev.get(cur)
            return list(reversed(path))
        cu = nodes[u]
        for v in (adj.get(u) or []):
            cv = nodes[v]
            dlat = (cu[1] - cv[1]) * 111.0
            dlon = (cu[0] - cv[0]) * 111.0 * math.cos(math.radians((cu[1] + cv[1]) / 2))
            nd = d + math.sqrt(dlat * dlat + dlon * dlon)
            if nd < dist.get(v, math.inf):
                dist[v] = nd
                prev[v] = u
                heapq.heappush(heap, (nd, v))

    return None


# ---------------------------------------------------------------------------
# Ferry / bus geometry  (shared Overpass route-relation strategy)
# ---------------------------------------------------------------------------

def get_ferry_geometry(lat1: float, lon1: float, lat2: float, lon2: float) -> list[list[float]]:
    """Return [[lon, lat], …] polyline following OSM ferry route geometry."""
    return _get_route_geometry("ferry", lat1, lon1, lat2, lon2)


def get_bus_geometry(lat1: float, lon1: float, lat2: float, lon2: float) -> list[list[float]]:
    """Return [[lon, lat], …] polyline following OSM bus route geometry."""
    return _get_route_geometry("bus", lat1, lon1, lat2, lon2)


def _get_route_geometry(
    route_tag: str,
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> list[list[float]]:
    """
    Three strategies tried in order:
      A  Route-relation strategy: query OSM route relations for *route_tag*
         (e.g. "ferry", "bus"), pick the best-fitting one, return trimmed geometry.
      B  Way route=* fallback: Dijkstra on ways tagged route=*route_tag*.
      C  ferry=yes way fallback (ferry only): Dijkstra on ways tagged ferry=yes.
         Many short island-hopper crossings use this tag instead of route=ferry.
    """
    try:
        return _via_route_relation_type(route_tag, lat1, lon1, lat2, lon2)
    except OverpassError:
        pass
    try:
        return _via_way_type_fallback(route_tag, lat1, lon1, lat2, lon2)
    except OverpassError:
        pass
    if route_tag == "ferry":
        return _via_ferry_yes_fallback(lat1, lon1, lat2, lon2)
    raise OverpassError(f"No {route_tag} route found between the two endpoints")


def _via_route_relation_type(
    route_tag: str,
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> list[list[float]]:
    # Clamp buffer: enough headroom to capture terminal areas, but not so large
    # that mega-routes (Stockholm–Turku) flood the result and cause timeouts.
    raw_buf = max(abs(lat1 - lat2), abs(lon1 - lon2)) * 0.5 + 0.15
    buf = min(raw_buf, 0.4)
    bbox = (
        min(lat1, lat2) - buf, min(lon1, lon2) - buf,
        max(lat1, lat2) + buf, max(lon1, lon2) + buf,
    )
    query = f"""
[out:json][timeout:{_TIMEOUT_QUERY}];
rel["route"="{route_tag}"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});
._;
out geom;
"""
    data = _overpass(query)
    relations = data.get("elements", [])

    best: Optional[list[list[float]]] = None
    best_score = math.inf
    for rel in relations:
        geom = _extract_geometry(rel, lat1, lon1, lat2, lon2)
        if geom and len(geom) >= 2:
            # Score by endpoint proximity: _trim guarantees geom[0] is the
            # point in the relation nearest (lon1,lat1) and geom[-1] nearest
            # (lon2,lat2), so a low score means the route actually connects
            # the requested ports. Scoring by total path length (the previous
            # approach) caused long open-sea crossings to lose to short coastal
            # hops that happened to fall inside the same bounding box.
            score = _sq(geom[0], [lon1, lat1]) + _sq(geom[-1], [lon2, lat2])
            if score < best_score:
                best_score = score
                best = geom

    if best is None:
        raise OverpassError(f"No {route_tag} route relation found in bounding box")
    return best


def _via_way_type_fallback(
    route_tag: str,
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> list[list[float]]:
    buf = 0.25
    bbox = (
        min(lat1, lat2) - buf, min(lon1, lon2) - buf,
        max(lat1, lat2) + buf, max(lon1, lon2) + buf,
    )
    query = (
        f"[out:json][timeout:{_TIMEOUT_QUERY}];"
        f'way["route"="{route_tag}"]'
        f"({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});"
        "out geom;"
    )
    try:
        data = _overpass(query)
    except OverpassError:
        raise

    ways = data.get("elements", [])
    if not ways:
        raise OverpassError(f"No {route_tag} ways found in bounding box")

    nodes: dict[str, list[float]] = {}
    adj:   dict[str, list[str]]   = {}
    for way in ways:
        prev: Optional[str] = None
        for pt in way.get("geometry", []):
            nid = f"{pt['lat']:.6f},{pt['lon']:.6f}"
            nodes[nid] = [pt["lon"], pt["lat"]]
            if prev is not None:
                adj.setdefault(prev, []).append(nid)
                adj.setdefault(nid,  []).append(prev)
            prev = nid

    if not nodes:
        raise OverpassError(f"No {route_tag} nodes found in bounding box")

    start_node = _nearest_node(nodes, lat1, lon1)
    end_node   = _nearest_node(nodes, lat2, lon2)
    path = _dijkstra(nodes, adj, start_node, end_node)

    if path:
        return [[lon1, lat1]] + [nodes[n] for n in path] + [[lon2, lat2]]
    raise OverpassError(f"No {route_tag} path found between endpoints")


def _via_ferry_yes_fallback(
    lat1: float, lon1: float,
    lat2: float, lon2: float,
) -> list[list[float]]:
    """Strategy C: Dijkstra on OSM ways tagged ferry=yes.

    Many short island-hopper crossings (e.g. Finnish/Åland archipelago ferries)
    tag the navigable route as ferry=yes on a way rather than using a
    route=ferry relation or way.  This is the last resort before giving up.
    """
    buf = min(max(abs(lat1 - lat2), abs(lon1 - lon2)) * 0.5 + 0.15, 0.4)
    bbox = (
        min(lat1, lat2) - buf, min(lon1, lon2) - buf,
        max(lat1, lat2) + buf, max(lon1, lon2) + buf,
    )
    query = (
        f"[out:json][timeout:{_TIMEOUT_QUERY}];"
        f'way["ferry"="yes"]'
        f"({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});"
        "out geom;"
    )
    try:
        data = _overpass(query)
    except OverpassError:
        raise

    ways = data.get("elements", [])
    if not ways:
        raise OverpassError("No ferry=yes ways found in bounding box")

    nodes: dict[str, list[float]] = {}
    adj:   dict[str, list[str]]   = {}
    for way in ways:
        prev: Optional[str] = None
        for pt in way.get("geometry", []):
            nid = f"{pt['lat']:.6f},{pt['lon']:.6f}"
            nodes[nid] = [pt["lon"], pt["lat"]]
            if prev is not None:
                adj.setdefault(prev, []).append(nid)
                adj.setdefault(nid,  []).append(prev)
            prev = nid

    if not nodes:
        raise OverpassError("No ferry=yes nodes found in bounding box")

    start_node = _nearest_node(nodes, lat1, lon1)
    end_node   = _nearest_node(nodes, lat2, lon2)
    path = _dijkstra(nodes, adj, start_node, end_node)

    if path:
        return [[lon1, lat1]] + [nodes[n] for n in path] + [[lon2, lat2]]
    raise OverpassError("No ferry path found between endpoints via ferry=yes ways")


# ---------------------------------------------------------------------------
# Shared utilities
# ---------------------------------------------------------------------------



def _straight(lat1: float, lon1: float, lat2: float, lon2: float) -> list[list[float]]:
    return [[lon1, lat1], [lon2, lat2]]


def _sq(a: list[float], b: list[float]) -> float:
    return (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2


_HEADERS = {"User-Agent": "ViewTripWeb/1.0 (https://github.com/viewtrip; route geometry resolver)"}


def _overpass(query: str) -> dict:
    try:
        resp = requests.post(
            _OVERPASS_URL,
            data={"data": query},
            headers=_HEADERS,
            timeout=_TIMEOUT_HTTP,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise OverpassError(f"Overpass query failed: {exc}") from exc
