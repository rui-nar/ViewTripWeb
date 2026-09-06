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
  `railway in (rail, narrow_gauge, light_rail)` without `service`,
  `route=train` relations, station/halt nodes with `uic_ref`.
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
  "schema": 1,
  "generated_at": "2026-09-06T18:00:00Z",
  "regions": [
    {
      "region": "europe/germany",
      "file": "germany-rail.osm.pbf",
      "source": "https://download.geofabrik.de/europe/germany-latest.osm.pbf",
      "source_date": "2026-09-05",
      "sha256": "...",
      "bytes": 10000000,
      "ways": 130713,
      "relations": 2179,
      "stations": 5483,
      "bbox": [5.87, 47.27, 15.04, 55.06]
    }
  ]
}
```

`bbox` is what Phase 3 uses to decide which region covers a coordinate, so it is
required and must be the extract's true extent, not the country's nominal one.

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
new service. One file per region: ways with geometry, a node table, station/UIC
lookup, and R-tree indices over way and station bounding boxes. An in-process LRU
holds the built graph for the most recently used regions.

**Open:** whether to persist the adjacency graph or rebuild it per region on load.
Rebuild is simpler and measured at 8.41 s for Germany; persisting trades disk and
complexity for latency. Decide with a measurement, not in advance.

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
