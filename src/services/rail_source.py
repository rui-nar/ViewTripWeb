"""Where ``get_rail_geometry`` gets its elements from (issue #345, Phase 3).

The three rail strategies in ``src/services/overpass_service.py`` ask five
questions and today Overpass answers all five over the network. Phase 2 built a
per-region SQLite store that answers the same five from disk. This module is the
seam between them: :class:`RailSource` is the contract, :class:`LocalRailSource`
implements it over ``RailStoreCache``, and ``OverpassRailSource`` — which lives
beside the queries it wraps, in ``overpass_service`` — implements it over the
network. The strategies themselves are unchanged.

The surface is deliberately the five questions and nothing else. It is not a
general OSM interface: there is no way to ask for a node, a tag or a way by id,
because no strategy asks for one.

Two decisions shape the local implementation, and both are about region
boundaries rather than about data:

**Region boxes overlap, so a coordinate does not name one region.** Luxembourg
City falls inside four configured regions' boxes; Bratislava three. Choosing one
by geometry is wrong at exactly the borders where it matters — a point in Germany
near Luxembourg would select Luxembourg, whose extract holds no German track. So
every region whose box reaches the query is asked, and the *data* decides:
nearest wins for a point, and a box query is answered from all of them with the
results merged. Merging is what keeps a cross-border route whole, and it has to
deduplicate, because Geofabrik's extracts overlap at borders and the same way is
in both files.

**A local miss falls back to Overpass, and that is not a special case.** Near-zero
regions are real — Cyprus publishes two rail ways, Iceland one — so "the store
answered, and the answer was nothing" is indistinguishable from "we do not hold
this". Rather than guess with a ways-count threshold, the resolver retries the
whole segment against Overpass whenever the local attempt degrades to a straight
line (see ``get_rail_geometry``). Everything this module treats as "not covered"
— no directory, no manifest, an entry marked ``empty``, a file the manifest names
and the directory does not hold — therefore lands in the same place.
"""
from __future__ import annotations

import json
import math
import os
from abc import ABC, abstractmethod
from typing import Iterable, Optional, Sequence

from src.rail.store import (
    _MAX_BBOX_VERTICES,
    _box,
    RailStore,
    RailStoreCache,
    RailStoreError,
)
from src.utils.logging import get_logger

_log = get_logger(__name__)

# Phase 1's artifact, and the two things this module reads from it: which
# regions exist, and where each one's *rail* reaches (its bbox is measured over
# rail ways, the same extent src/rail/builder.py records in the store).
MANIFEST_NAME = "manifest.json"
# Schema 2 added `status`, and with it entries that describe a region holding no
# rail rather than a published file. A schema we do not recognise is refused
# outright: a manifest read with the wrong shape would silently claim coverage
# it does not have, which is the failure mode that looks exactly like success.
MANIFEST_SCHEMA = 2
_STATUS_OK = "ok"

# How far beyond a segment's endpoints to look for regions that may hold a
# relation the segment needs. Strategy B searches relations within 25 km of each
# endpoint, so a region whose data reaches that far can be the one holding the
# relation's geometry — including the neighbouring country, whose box need not
# contain the endpoint at all. Under-scoping here is the cross-border failure in
# its quietest form: the relation is found by id and comes back with no geometry.
_RELATION_SCOPE_M = 25_000


class RailSourceError(Exception):
    """The local source cannot be used at all — bad manifest, bad directory."""


class RailSourceOverload(Exception):
    """A bounding-box query holds more data than a worker can hold.

    Distinct from every other failure because it must *not* fall back to
    Overpass. The ceiling is a bound on our own memory (``_MAX_BBOX_VERTICES``:
    ~268 bytes per vertex, and as much again once ``_build_rail_graph`` runs), so
    asking Overpass the same question and getting an answer is the worse
    outcome — it re-creates the allocation the ceiling refused, on the same
    worker, after paying for the largest query we know how to ask.
    """


class RailSource(ABC):
    """The five questions the rail strategies ask, and nothing more.

    Element shapes are Overpass's ``out geom`` shapes throughout, because
    ``_build_rail_graph`` and ``_extract_relation_geometry`` consume them
    directly and this phase changes only where the elements come from.
    """

    @abstractmethod
    def nearest_station(
        self, lat: float, lon: float, radius_m: float = 5000
    ) -> Optional[dict]:
        """Nearest station carrying a ``uic_ref``: ``{"lat", "lon", "uic"}``."""

    @abstractmethod
    def relations_for_uic_pair(
        self, uic1: str, uic2: str, near: Sequence[tuple[float, float]]
    ) -> list[dict]:
        """Route relations whose stops include both UIC codes, with geometry.

        *near* is where the segment is — its endpoints as (lat, lon). Overpass
        has no use for it; the local source needs it to know which regions could
        hold the answer, and no coordinate is derivable from a UIC code alone.
        """

    @abstractmethod
    def relations_near(
        self, lat: float, lon: float, radius_m: float = 25_000
    ) -> set[int]:
        """Ids of route relations passing within *radius_m* of the point."""

    @abstractmethod
    def relation_geometry(
        self, rel_ids: Sequence[int], near: Sequence[tuple[float, float]]
    ) -> list[dict]:
        """Those relations, with their member ways' geometry. *near*: see above."""

    @abstractmethod
    def ways_in_bbox(
        self, min_lat: float, min_lon: float, max_lat: float, max_lon: float
    ) -> list[dict]:
        """Railway track overlapping the box, in ``_build_rail_graph``'s shape."""


# ---------------------------------------------------------------------------
# Coverage — which regions the local data directory holds
# ---------------------------------------------------------------------------

def load_coverage(directory: str) -> list[tuple[str, tuple[float, float, float, float]]]:
    """Regions this directory covers, as (region, (min_lat, min_lon, max_lat, max_lon)).

    Empty means "covered nowhere", which is a legitimate answer and not an
    error: a deployment that has not fetched the data yet, or a manifest whose
    regions are all ``empty``. Anything actively wrong — unparseable JSON, a
    schema we do not know — raises instead, because reading it wrongly would
    claim coverage we do not have.

    The manifest's bbox is ``[min_lon, min_lat, max_lon, max_lat]``; the store
    speaks (lat, lon) pairs, so it is transposed once, here.
    """
    path = os.path.join(directory, MANIFEST_NAME)
    if not os.path.isfile(path):
        _log.info("no rail manifest at %s — local rail coverage is empty", path)
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            manifest = json.load(handle)
    except (OSError, ValueError) as exc:
        raise RailSourceError(f"{path}: {exc}") from exc
    schema = manifest.get("schema")
    if schema != MANIFEST_SCHEMA:
        raise RailSourceError(
            f"{path}: manifest schema {schema!r}, expected {MANIFEST_SCHEMA}")

    coverage = []
    for entry in manifest.get("regions", []):
        # `empty` is Phase 1 saying "this region has no rail at all" (Andorra,
        # Malta, the Azores, Liechtenstein). It is an answer, not a gap — but it
        # is still not coverage, because there is no file and nothing to route on.
        if entry.get("status", _STATUS_OK) != _STATUS_OK:
            continue
        bbox = entry.get("bbox") or []
        if len(bbox) != 4:
            _log.warning("rail manifest entry %r has no usable bbox — skipped",
                         entry.get("region"))
            continue
        min_lon, min_lat, max_lon, max_lat = (float(v) for v in bbox)
        coverage.append((entry["region"], (min_lat, min_lon, max_lat, max_lon)))
    return coverage


def _overlaps(a: tuple[float, float, float, float],
              b: tuple[float, float, float, float]) -> bool:
    """Do two (min_lat, min_lon, max_lat, max_lon) boxes intersect?"""
    return a[0] <= b[2] and b[0] <= a[2] and a[1] <= b[3] and b[1] <= a[3]


def _scope(near: Sequence[tuple[float, float]]) -> tuple[float, float, float, float]:
    """The box a relation serving these points could be held in.

    Each point is widened by ``_RELATION_SCOPE_M`` with the store's own box
    maths, so the longitude span accounts for latitude exactly as the store's
    queries do.
    """
    boxes = [_box(lat, lon, _RELATION_SCOPE_M) for lat, lon in near]
    return (
        min(b[0] for b in boxes), min(b[1] for b in boxes),
        max(b[2] for b in boxes), max(b[3] for b in boxes),
    )


# ---------------------------------------------------------------------------
# The local source
# ---------------------------------------------------------------------------

class LocalRailSource(RailSource):
    """Answers from the region stores in *directory*.

    Raises :class:`RailSourceError` when the directory's manifest cannot be
    trusted; a directory with no manifest is not an error, it simply covers
    nothing and every query returns nothing, which the resolver reads as "ask
    Overpass".

    The store cache keeps its default bound on open files. A query spanning four
    regions therefore reopens some of them — 0.8 ms each, measured — which is the
    right trade against holding 49 files open to save it.
    """

    def __init__(self, directory: str | os.PathLike,
                 cache: Optional[RailStoreCache] = None) -> None:
        self.directory = str(directory)
        self.coverage = load_coverage(self.directory)
        self._cache = cache if cache is not None else RailStoreCache(self.directory)

    # -- region selection ------------------------------------------------

    def regions_for(self, box: tuple[float, float, float, float]) -> list[str]:
        """Every region whose rail reaches into *box*, in a stable order."""
        return sorted(region for region, bbox in self.coverage if _overlaps(bbox, box))

    def _stores_for(self, box: tuple[float, float, float, float]) -> Iterable[RailStore]:
        """Open stores for those regions, skipping the ones we do not hold.

        A manifest entry whose file is absent — a partial download, a release
        asset that failed to attach — is coverage on paper only, so it is
        skipped here and the query is answered from whatever else overlaps. The
        resolver's Overpass fallback covers the case where that is nothing.
        """
        for region in self.regions_for(box):
            store = self._cache.get(region)
            if store is None:
                _log.warning("rail region %s is in the manifest but not in %s",
                             region, self.directory)
                continue
            yield store

    def _stores_near(self, lat: float, lon: float, radius_m: float) -> Iterable[RailStore]:
        return self._stores_for(_box(lat, lon, radius_m))

    # -- the five questions ----------------------------------------------

    def nearest_station(
        self, lat: float, lon: float, radius_m: float = 5000
    ) -> Optional[dict]:
        """Nearest across every overlapping region — the data picks the region.

        Each store already ranks its own candidates by squared degrees, which is
        what ``_find_station_near`` minimises, and that ordering is a total order
        over all of them: the smallest of the per-region winners is the winner
        one merged store would have returned.
        """
        best: Optional[dict] = None
        best_sq = math.inf
        for store in self._stores_near(lat, lon, radius_m):
            found = store.nearest_station(lat, lon, radius_m)
            if found is None:
                continue
            sq = (found["lat"] - lat) ** 2 + (found["lon"] - lon) ** 2
            if sq < best_sq:
                best, best_sq = found, sq
        return best

    def relations_for_uic_pair(
        self, uic1: str, uic2: str, near: Sequence[tuple[float, float]]
    ) -> list[dict]:
        box = _scope(near)
        stores = list(self._stores_for(box))
        rel_ids = sorted({
            rel_id for store in stores
            for rel_id in store.relations_for_uic_pair(uic1, uic2)
        })
        if not rel_ids:
            return []
        return _merge_relations(store.relation_geometry(rel_ids) for store in stores)

    def relations_near(
        self, lat: float, lon: float, radius_m: float = 25_000
    ) -> set[int]:
        """The union, not one region's answer.

        Strategy B intersects the two endpoints' sets. A cross-border relation is
        in both countries' extracts, so the union is what lets the intersection
        find it; one region's answer would drop it at exactly the border.
        """
        found: set[int] = set()
        for store in self._stores_near(lat, lon, radius_m):
            found |= store.relations_near(lat, lon, radius_m)
        return found

    def relation_geometry(
        self, rel_ids: Sequence[int], near: Sequence[tuple[float, float]]
    ) -> list[dict]:
        if not rel_ids:
            return []
        return _merge_relations(
            store.relation_geometry(rel_ids) for store in self._stores_for(_scope(near)))

    def ways_in_bbox(
        self, min_lat: float, min_lon: float, max_lat: float, max_lon: float
    ) -> list[dict]:
        """Every overlapping region's track, merged and deduplicated by way id.

        The dedup is not defensive: Geofabrik's country extracts overlap at
        borders, so a way near one is genuinely in two files, and counting it
        twice would put two identical edges in the graph and two copies of its
        vertices in memory.

        The vertex ceiling applies to the merged result, not to each region's
        share of it, so four regions cannot together allocate what one is refused.
        """
        box = (min_lat, min_lon, max_lat, max_lon)
        ways: dict[int, dict] = {}
        budget = _MAX_BBOX_VERTICES
        for store in self._stores_for(box):
            try:
                found = store.ways_in_bbox(*box, max_vertices=budget)
            except RailStoreError as exc:
                # ways_in_bbox raises for one reason: the box is too big. The
                # store was opened successfully, so this is not a broken file.
                raise RailSourceOverload(str(exc)) from exc
            for way in found:
                if way["id"] not in ways:
                    ways[way["id"]] = way
                    budget -= len(way["geometry"])
        # By id, so the graph is built in one order whatever order the regions
        # were read in — the same order Overpass returns elements in.
        return [ways[way_id] for way_id in sorted(ways)]


def _merge_relations(per_region: Iterable[list[dict]]) -> list[dict]:
    """One entry per relation id, its members filled in from every region.

    A relation crossing a border is in both countries' extracts, and each holds
    only its own side's member ways — the gap Phase 1 measured and cannot close
    from one file. Overpass, asked for that relation, returns all of it. Filling
    each unheld member from whichever region does hold it is therefore not a new
    behaviour, it is the parity this phase is for.
    """
    merged: dict[int, dict] = {}
    for relations in per_region:
        for rel in relations:
            current = merged.get(rel["id"])
            merged[rel["id"]] = rel if current is None else _merge_members(current, rel)
    return [merged[rel_id] for rel_id in sorted(merged)]


def _merge_members(a: dict, b: dict) -> dict:
    """*a* with every member it lacks taken from *b*, where the two agree.

    Both list the relation's membership in full and in member order — the store
    records a member it does not hold rather than skipping it, precisely so the
    lists line up — so the merge is positional, and guarded by the way id in case
    the two extracts were cut from different days' data.
    """
    if len(a["members"]) != len(b["members"]):
        return a if a["missing_members"] <= b["missing_members"] else b
    members = [
        mb if (not ma["held"] and mb["held"] and ma["ref"] == mb["ref"]) else ma
        for ma, mb in zip(a["members"], b["members"])
    ]
    return {**a, "members": members,
            "missing_members": sum(1 for m in members if not m["held"])}
