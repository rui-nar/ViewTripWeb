# Local rail data — implementation plan

Tracking issue: **#345**. This plan covers acquiring the data, storing it,
keeping it current, changing the resolver to use it, and the tests at each step.

The measurements it rests on are in #345 and are not repeated here beyond what a
decision needs.

---

## The shape of the thing

Today `get_rail_geometry` asks Overpass three questions and Overpass answers them
over the network:

1. *What station is near this coordinate, and what is its UIC code?* (`_enrich_uic`)
2. *Which `route=train` relation covers both endpoints?* (strategies A and B)
3. *Give me every railway way in this bounding box.* (strategy C)

Only question 3 is expensive, and all three are lookups against a slowly-changing
dataset. **Overpass is a data source here, not an algorithm** — `_build_rail_graph`,
`_nearest_node` and `_dijkstra` are already ours and already run locally. So this
is a substitution of the source, not a rewrite of the resolver.

That framing sets the acceptance bar: **the strategies keep their current shape and
their current tests; only where the elements come from changes.**

---

## Phase 0 — Coverage *(DECIDED)*

**Europe, per-country files. Overpass remains the fallback outside Europe.**
Coverage widens gradually once this is proven in production.

That choice is deliberately conservative in both directions. Europe is where the
product's trips are, and per-country granularity is what keeps RAM bounded
(Phase 2) — Germany alone is 319 MB resident, so a single Europe-wide graph is
not an option. Keeping Overpass for the rest of the world means a user who
travels outside coverage still gets a route rather than an apology, and it
reduces the migration's blast radius to "the regions we hold".

The fallback is safe *because* of the volume maths that motivated this work: once
European segments resolve locally, Overpass sees a handful of requests a day
instead of several per resolve. That is comfortably inside fair use, so the
dependency stops being a structural ban risk even though it still exists.

**Consequences that bind later phases:**

- Region selection must be able to say "not covered" and hand off, so the source
  interface in Phase 3 needs a third outcome besides success and failure.
- Coverage is configuration, not code. Adding a country is a manifest change and
  a rebuild, never a deploy of new logic.
- The comparison in Phase 4 only applies within covered regions; outside them
  both sources are the same source.

---

## Phase 1 — The extract pipeline *(CI, not the VPS)*

**The 34.9 GB Europe raw file must never touch the VPS.** It does not fit
alongside prod and val on 40 GB. Build the artifact in CI and ship only the result.

- A scheduled GitHub Actions workflow downloads the Geofabrik extracts for the
  regions from Phase 0, filters each to rail with the `osmium` CLI (not pyosmium —
  the spike measured 2,022 s for Germany in Python; the C++ tool is far faster),
  and publishes the filtered artifacts.
- Filter selection **must match the current Overpass queries exactly**, or results
  change for reasons unrelated to this work:

  | | selection | serves |
  |---|---|---|
  | ways | `railway` in `(rail, narrow_gauge, light_rail)` **without** `service` | `_via_coordinate_fallback` |
  | relations | `route` in `(train, railway, light_rail)` | `_route_relation_segment`, `_via_train_relations_endpoints` |
  | nodes | **any** node carrying `uic_ref` | `_route_relation_segment` |
  | stations | node, **way or relation** with `railway` in `(station, halt)` and `uic_ref` | `_find_station_near` |

  The last two rows are wider than they look and the width is load-bearing. An
  earlier version of this contract specified "station/halt nodes with `uic_ref`"
  for both, derived from `_find_station_near` alone — but `_route_relation_segment`
  matches `node["uic_ref"=X]` with **no** railway filter, and relations reference
  the *stop* node rather than the station node. Stop nodes are routinely untagged
  as stations: in Luxembourg, 20 relation members carry a `uic_ref` and none is
  tagged `station` or `halt`, so the narrow filter made strategy A find nothing
  where Overpass finds relations today. `_find_station_near` likewise matches ways
  and relations, not just nodes, so polygon-mapped stations were being dropped.

  Verify any change to this table against `src/services/overpass_service.py`
  directly — the queries there are the specification, not this document.
- Publish per-region, versioned by the source extract's date, with a manifest
  recording region, source date, checksum and size.

**Where the artifact lives** is a real decision with a wrong answer: baking it into
the Docker image couples data refresh to a code release and inflates every image.
Prefer a release asset or object store the container fetches on boot and caches on
the mounted volume, so data and code move independently.

### Tests
- The filter selection is asserted against a checked-in fixture extract (a small
  bbox, a few hundred KB) so a tag-selection change fails CI rather than silently
  altering coverage.
- Manifest schema and checksum verification.
- A guard that the workflow never writes a raw extract into the image or the repo.


---

## The Phase 1 / Phase 2 contract

Fixed here so the two phases can be built independently and in parallel.

**Phase 1 produces**, per region, and publishes as a versioned artifact:

- `<region>-rail.osm.pbf` — the filtered extract.
- `manifest.json` — one entry per region:

```json
{
  "schema": 2,
  "generated_at": "2026-09-06T18:00:00Z",
  "regions": [
    {
      "region": "europe/germany",
      "status": "ok",
      "file": "germany-rail.osm.pbf",
      "source": "https://download.geofabrik.de/europe/germany-latest.osm.pbf",
      "source_date": "2026-09-05",
      "sha256": "...",
      "bytes": 10000000,
      "ways": 130713,
      "relations": 2179,
      "stations": 5483,
      "bbox": [5.87, 47.27, 15.04, 55.06]
    },
    {
      "region": "europe/andorra",
      "status": "empty",
      "source": "https://download.geofabrik.de/europe/andorra-latest.osm.pbf",
      "source_date": "2026-09-05"
    }
  ]
}
```

### Three outcomes, not two

A region's build ends as `ok`, `empty` or `failed`, and the manifest records the
first two. **`empty` is the Phase 0 "third outcome" made concrete on the data
side**: the pipeline ran correctly and the region holds **no rail ways**.

- `ok` — rail ways exist. The `.pbf` is published and the entry is the full
  record above.
- `empty` — no rail ways. The matrix job exits **0**, **no artifact is
  published**, and the entry carries `status: "empty"` with no `file`, `sha256`,
  `bytes` or `bbox` — there is nothing to download and nothing it covers.
  **Phase 3 must read an `empty` region as "we know there is no rail here":**
  fall back to Overpass exactly as for an unlisted region, and never treat it as
  a build that has yet to happen.
- `failed` — anything else. The job exits non-zero and the region is simply
  absent from the manifest.

The discriminator is rail ways and nothing else, which is the same predicate
`src/rail/builder.py` refuses a store on (`no railway ways — not a rail
extract`). The two must agree or Phase 1 publishes files Phase 2 rejects: four
configured regions sit in that gap today — Andorra, Malta and the Azores have no
railway at all, and Liechtenstein's only line is currently tagged
`railway=construction`, which gives it stations and UIC nodes but no ways.

Absence therefore means failure, and the publish job treats it that way: a run
whose manifest covers fewer regions than the run was supposed to build refuses
to publish and names them, because an uncovered region falls back to Overpass —
the service this whole plan exists to stop depending on. A subset rebuild
(`workflow_dispatch` with `regions: europe/denmark`) merges into the manifest of
the release it patches rather than replacing it.

### `bbox`

`bbox` is what Phase 3 uses to decide which region covers a coordinate, so it is
required for an `ok` region and must be the extract's true extent, not the
country's nominal one. It is `[min_lon, min_lat, max_lon, max_lat]` **over the
nodes of the rail ways only** — the same extent `src/rail/builder.py` writes to
the store's `meta` and `RailStore.bbox` reports. Bare `uic_ref` nodes and
platform or siding geometry are excluded from it deliberately: they are in the
file for other reasons and would claim coverage the routable data does not have.

**Region boxes overlap, and the tiebreak is Phase 3's to decide.** These are
country extracts, so their true extents interleave: Luxembourg City falls inside
four configured regions' boxes, Bratislava three, Zurich three. Nothing in
Phase 1 or Phase 2 ranks them — "which region for this coordinate" has no
defined answer yet, and picking the first match in manifest order would be an
accident rather than a decision. Phase 3 owns it (see *Region selection* below).

**Phase 2 consumes** a filtered `.pbf` and owns everything after it: the store
format, the builder, and the reader. **Where the store is built — in CI as part of
the artifact, or on the box at first use — is Phase 2's decision**, to be made on a
measurement rather than in advance. If it turns out to belong in CI, Phase 1 gains
one step that calls Phase 2's builder; nothing else moves.

Neither phase may import from the other except through these two surfaces.


## Phase 2 — The local store

The spike used a pickle of way geometries. That was right for measuring and wrong
to ship: pickle is not a stable format, loads all-or-nothing, and 319 MB resident
for Germany is the whole budget for a single country.

Requirements, in priority order:

1. **Bounded memory.** Never hold more than a couple of regions at once.
2. **Fast point lookup.** `_nearest_node` is a linear scan today — 1.43 s over
   Germany's 1.1 M nodes, called twice per resolve. This is the single largest
   avoidable cost and needs a spatial index.
3. **Fast load.** A cold region should cost well under the 8.41 s the spike's
   naive build took.
4. **Inspectable.** A format we can query by hand when a route looks wrong.

SQLite with an R-tree index fits all four, matches the existing stack, and needs no
new service. One file per region — `src/rail/store.py` reads what
`src/rail/builder.py` writes: ways with packed geometry, station/UIC lookup,
relation membership, and R-tree indices over way and station bounding boxes.
An in-process LRU bounds how many region files are open at once.

**Decided, on measurements (see the PR for issue #345 Phase 2):**

- **The store holds no graph**, which answers the open question about persisting
  the adjacency graph: neither. Strategy C already works on a bounding box, so a
  bbox query returns only the ways the route needs — Hamburg→Flensburg is 4,422
  of Germany's 130,713 ways and a 33.5k-node graph, not the country's 1,137,563.
  Resolving it costs 62 MB resident against the 319 MB the whole-country graph
  needs, and 0.15 s end to end. Requirement 3 (fast load) stops applying: there
  is nothing to load, and opening a region is 0.8 ms.
- **The memory did not disappear, it moved to the caller's bounding box** — about
  268 bytes per vertex, doubling once `_build_rail_graph` runs. Hamburg→Munich is
  284,607 vertices (~150 MB, measured 204 MB resident for the whole resolve); the
  whole-Germany box is 1,270,497 (~680 MB) on a 1 GB worker. `ways_in_bbox`
  therefore enforces its own vertex ceiling and raises rather than allocate, and
  `_RAIL_BBOX_MAX_AREA` in the resolver guards the same failure from the other
  end: it is a memory bound now, not an Overpass workaround, and must survive
  Phase 6.
- **A spatial index replaces the linear snap, at parity.** `nearest_node` over
  Germany is 0.4–1.5 ms against 0.67 s for the same scan over the whole-country
  graph in this process (1.43 s in the spike), and it returns the *identical*
  vertex — including `_nearest_node`'s squared-degree ordering, which is wrong as
  geometry and kept anyway because this phase substitutes the source and nothing
  else. Ranking by metres instead moved 0.53% of ±200 m snaps into a different
  connected component. Snapping is Phase 4's to fix, against a stable baseline.
- **The store is built in CI**, as one more step in the Phase 1 pipeline calling
  `python -m src.rail.builder`. Germany builds in 23.9 s at 196 MB peak — small
  enough that first-use building on the box would work, and pointless: it would
  put the `.pbf` and the builder on a VPS that needs neither, and pay that cost
  again after every container restart with an empty volume. Cost of the choice is
  transfer size: the store is larger than the extract it is built from (Germany
  58 MB from 23 MB, 28 MB gzipped).

### Tests
- Round-trip: filtered extract → store → the same element shapes
  `_build_rail_graph` consumes today.
- Spatial index correctness: nearest-station and nearest-node queries against
  brute-force results on a fixture region.
- LRU eviction bounds resident memory below a stated ceiling.
- Load time for the largest region stays under budget (a perf test with a
  generous threshold, to catch regressions rather than police milliseconds).

---

## Phase 3 — Resolver integration

Introduce a source interface with two implementations — the existing Overpass one
and the local one — so the three strategies are unchanged and switchable by config.
That is what makes the comparison period in Phase 4 possible at all.

- `_enrich_uic` becomes a local station lookup. Note the spike's finding that UIC
  coverage swings from 0.3 % (Denmark) to thousands of stations (Germany); locally
  the lookup is free either way, so no behaviour need change.
- Strategies A and B query local relations.
- Strategy C loads the region's graph instead of issuing a bbox query.
- **Region selection** from the segment's endpoints, including the case where a
  route crosses a border — the plan's first genuinely new logic. Two adjacent
  regions must be loadable and joinable, or cross-border rail silently degrades.
  Region boxes overlap (see the contract above), so selection needs a stated
  tiebreak, and an `empty` region means "no rail here, use Overpass" rather than
  "not built yet".

### Tests
- Every existing rail test in `tests/test_vr_hafas.py`,
  `tests/test_overpass_fallback.py` and the resolve tests passes against the local
  source, with the Overpass source still passing too.
- Cross-border resolution over a fixture spanning two regions.
- Outside-coverage behaviour matches the Phase 0 decision.
- No network access: a test that fails if the local source opens a socket.

---

## Phase 4 — Comparison and cutover

Do not switch on faith. For a period, resolve through both sources and record where
they differ — strategy chosen, point count, path length, degraded flag.

This is also where the **known routing defects** get addressed, because they become
cheap to iterate on (0.15 s per experiment instead of a 45 s network round trip):

- **Snapping.** `_nearest_node` picks the geometrically closest node regardless of
  which connected component it is in, so a siding beside the platform beats the
  through line. Fix: prefer a node that can reach the destination.
- **Fragmentation.** Denmark 50 components (largest 65.6 %), Germany 1,143
  (87.6 %). Decide deliberately whether to include `service` ways — the spike
  showed doing so raises the largest component but breaks routes that previously
  worked, because it interacts with the snapping bug.

Treat these as **quality work enabled by the migration, not part of it** — land the
substitution first, with parity, then improve routing against a stable baseline.

### Tests
- A corpus of real segments with expected strategy and rough geometry, run against
  both sources, asserting parity within tolerance.
- Regression tests for each routing defect, written to fail against current
  behaviour first.

---

## Phase 5 — Maintenance

- Scheduled refresh (monthly is ample; rail alignment changes over years).
- Metrics: region load time, cache hit rate, resolve duration, outside-coverage
  rate, and **data age** — a silently stale extract is the failure mode here, and
  it looks exactly like success.
- An alert on data age exceeding the refresh interval.
- Document the refresh procedure and the manual-rebuild path in
  `docs/DEPLOYMENT_VPS.md`.

---

## Phase 6 — Retire the scaffolding

Once the local source is authoritative, most of the Overpass remediation exists
only to manage a quota we no longer depend on: the resolve deadline, 429 backoff,
host cooldowns, `upstream_slots`, the concurrency limiter, and arguably
`upstream_cache`.

Keep the Overpass source itself if it remains the outside-coverage fallback — but
then it serves a handful of requests a day rather than several per resolve, which
is comfortably inside fair use and stops the ban risk being structural.

---

## Risks

| risk | mitigation |
|---|---|
| Local results differ from Overpass in edge cases | Phase 4 comparison period; parity tests before cutover |
| Extract goes stale unnoticed | data-age metric and alert; it is the failure that looks like success |
| RAM regression as coverage grows | LRU ceiling test in Phase 2 |
| CI build cost grows with coverage | per-region artifacts, refreshed independently |
| A user travels outside coverage | explicit Phase 0 decision, not an accident |

## What this does not change

HAFAS/MOTIS train lookup is a separate service and is untouched. The
`route_quality` modelling (D2), the job-liveness endpoint (D3) and distinct map
styling for approximate routes (D4) remain wanted and are independent of this work.
