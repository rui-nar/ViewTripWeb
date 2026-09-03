# Map load performance: audit and staged plan (issue #276)

Why the map still stutters for several seconds after the loading spinner
clears, what actually causes it, and the order in which to fix it.

Written after the round of ANR fixes that landed through #256–#290. Those
removed the hard blockages; what remains is a rhythm of short stalls during
the first ~10 s of a trip. This document is the diagnosis and the plan, not
a changelog.

## The real timeline of a cold open

`ProjectNotifier.load()` is a three-phase pipeline. Phase 1 clears the
spinner; phases 2 and 3 keep running afterwards, and that is where the
remaining jank lives.

| t | What happens | Runs on |
|---|---|---|
| 0 | `load()` clears state, notifies | UI isolate |
| ~1–2 s | `/meta` + `/geo/project/low-res` land, `jsonDecode` each | **UI isolate** |
| ~2 s | `isLoading = false` — spinner disappears | — |
| | **the user believes loading is finished here** | |
| ~2–6 s | `getGeo` → full-res GeoJSON `jsonDecode` + `expandEncodedActivities` (Google-polyline decode of every activity) | **UI isolate** |
| | ~8 progressive batches: geo swap → `notifyListeners()` → full map + panel + chart rebuild, 80 ms apart | UI isolate |
| | final pass: authoritative geo swap → another full rebuild | UI isolate |
| ~6–15 s | `getDetails` → the **~12 MB** details payload, `jsonDecode` | **UI isolate** |
| | `_buildFullTrack` / `computeElevationSpots` | worker isolate |
| | final `notifyListeners()` → full rebuild | UI isolate |

Issue #276 reports "I see the elevation curve go low-res to high-res and
after that I can move around" — that is the last row. Everything above it is
the residual jerkiness.

## Root causes, ranked

### 1. The decodes were never moved off the UI isolate — only the derived computations were

`ApiClient._handle` does a bare `jsonDecode(res.body)` for *every* endpoint,
including the ~12 MB details payload and the full-res geo. `ProjectService.getGeo`
then runs `expandEncodedActivities` — a polyline decode over potentially
300k+ points — inline immediately after.

Previous rounds correctly moved `buildFullTrackResult`, `hitTestMapTap`,
`computeElevationSpots` and `decimatePolylinePoints` behind `compute()`.
Those are the cheap half. The parse that *produces their input* is the
largest single main-thread block in the session and has no threshold guard
at all.

Corollary worth remembering: a **warm** open is smoother than a cold one,
because `project_cache_store_native.dart` gunzips and decodes via
`compute()`. The disk path is protected; the network path is not.

### 2. The progressive geo reveal is now pure cost

`_loadFullGeoProgressively` stages ~8 geo swaps 80 ms apart. That made sense
when the upgrade genuinely trickled in. Today the whole payload has already
arrived *and been parsed* before the first batch fires, so the staging buys
no perceived progress and costs 8 full-tree rebuilds — every polyline spec,
every marker spec, a `compute()` decimation hop, `ActivityPanel`,
`ElevationChart`.

This is the specific cause of the "small local blocks and unblocks" symptom:
it is a metronome of hitches roughly 640 ms wide, because the cause literally
is one.

### 3. `_waitForCameraIdle` defers jank rather than removing it

It polls every 100 ms and gives up after 2 s. Pan continuously and the whole
rebuild lands mid-gesture at t+2 s anyway. Deferral without a cheaper rebuild
only moves the stall — and the polling is itself work competing with the
gesture it is trying to stay out of the way of.

*(Fixed in Phase 2a: the wait is now event-driven off the camera-idle
callback, with the same cap.)*

### 4. One god-notifier makes every update a whole-screen update

`ProjectNotifier` is ~2700 lines with ~90 `notifyListeners()` calls, and
`app_screen.dart` wraps `ManageMapPanel` in a plain `Consumer`, so *any*
notification rebuilds the map.

The `identical()`-guard cache in `map_panel.dart` — roughly 20 `_lastX`
fields — exists purely to undo that over-broad notification. It is
compensation, not architecture, and it fails exactly when it matters: a geo
swap changes `geo`'s identity, so `geoOrStyleChanged` is true and everything
rebuilds from raw GeoJSON.

### 5. Geometry lives as untyped GeoJSON and is re-walked on every geo swap

`_buildPolylineSpecs`, `_buildActivityMarkerSpecs` and `buildFullTrackResult`
each walk `f['geometry']['coordinates']` with `as num` casts per coordinate
and allocate a `LatLng` per point.

**Correction to this document's first draft.** It originally claimed every
*rebuild* is O(total points). That is wrong: `memoCoordsToLatLng` already
memoizes the conversion on the identity of each feature's coords list, so
only a *changed* feature is re-converted. Measured on a 100-activity /
500k-point trip: a cold conversion costs ~83 ms, a warm rebuild ~0.1 ms.

The real cost is therefore one cold conversion per geo swap, not per rebuild
— which is exactly why it mattered that Phase 2a cut the number of swaps from
nine to one, and why Phase 2b is about moving that single conversion off the
UI isolate rather than restructuring the storage.

### 6. No zoom-adaptive level of detail

`kMaxTotalPolylinePoints` decimates once to a flat 6000-point budget for the
whole trip, viewport-independent. Zoomed out we render detail nobody can see;
zoomed in we have permanently lost detail. Memory markers are full widgets
with network thumbnails, built for the entire trip regardless of viewport.

### 7. Two platform caveats

- **`compute()` runs inline on Flutter web.** Every isolate guard in this
  codebase is a no-op there, and `project_cache_store_stub.dart` means web
  has no disk cache either. Web is the unprotected platform.
- The manage basemap is parked on `VectorTileLayerMode.vector`
  (`basemaps.dart`), which by that file's own comment repaints the whole
  basemap on every pumped frame at ~70 ms/frame on CanvasKit.

## The architectural take

One invariant is missing, and everything above is a symptom of its absence:

> **The client should never fetch, parse, or hold geometry at higher
> resolution than the current viewport can display.**

Today it is inverted: download the entire trip at full resolution, parse all
of it on the UI thread, then throw ~95% of it away (decimate to 6000 points,
downsample elevation to N spots). Every fix so far has been about making the
throwing-away cheaper. The long game is to not fetch it.

The machinery for that already exists. `src/tile_renderer.py` renders and
caches raster track tiles with background pre-render and edit invalidation.
`MapPanel` already accepts `trackTileUrlTemplate`, and `selectedOnly:
tilesActive` is already wired into `_stylePolylines`. It is only exposed to
share links. Promoting it to authenticated projects turns the base track into
tiles — constant client memory, instant pan, no client geometry cost — with
full-res vector geometry fetched only for the *selected* activity or day,
which is the only thing that needs hit-testing.

## Staged plan

Each phase is independently shippable and independently verifiable. The
ordering is deliberate: the later phases are much cheaper to build once the
earlier ones have simplified what they act on.

### Phase 0 — make it measurable (prerequisite)

Extend `perf_timing.dart` from percentile dumps to **named phase spans**:
`decode_meta`, `decode_geo`, `expand_polylines`, `decode_details`,
`apply_geo`, `build_specs`, `style_markers`.

*Verify:* a synthetic large-trip fixture, and a test asserting no single
main-isolate span exceeds the frame budget. Without this, every phase below
is unfalsifiable and the whole area regresses again silently.

**Reading the numbers on a real device.** Recording is on in every build, not
just `--dart-define=PERF_TIMING` ones — each span wraps a multi-millisecond
fetch, decode or build, so a Stopwatch and a map insert are far below the
noise floor of what they measure. After opening a trip, the last load's
report is in **Settings → Performance**, with a Copy button. A
dart-define-gated `debugPrint` cannot diagnose the builds that actually need
it: the ones installed on a phone with no debugger attached.

Read it as two separate things. **Blocking** spans are UI-isolate stalls —
those are jank, and anything over 16.7 ms dropped a frame. **Stage** spans
are wall clock and include isolate hops, so a multi-second `decode_geo` that
ran on a worker costs zero frames. The report says explicitly which blocking
spans, if any, went over budget.

### Phase 1 — move decode off the UI isolate

Fetch heavy payloads as bytes and do `utf8.decode → jsonDecode → domain
transform` in **one** isolate hop, returning typed data rather than a `Map`
tree where practical (a `Map<String, dynamic>` crossing an isolate boundary
is deep-copied; `Uint8List`/`Float64List` transfer near-free). Route
`getGeo`, `getDetails` and `getLowResGeo` through it, folding
`expandEncodedActivities` into the same hop.

*Verify:* `decode_geo` and `decode_details` spans disappear from the UI
thread; #276's repro — pan immediately after the spinner clears — is smooth.

### Phase 2a — drop the progressive reveal *(done)*

Delete the 8-batch reveal in favour of the single atomic swap the code
already performed as its "final pass", and replace `_waitForCameraIdle`'s
poll loop with an event-driven wait on the camera-idle callback (same cap, no
timer storm).

*Verified:* a test asserting listeners are handed at most two distinct `geo`
objects across a whole load — the low-res one, then the full-res one. On the
batched implementation the same test reports **9**.

**Rejected: `SchedulerBinding.scheduleTask(..., Priority.idle)`.** That was
the original plan — let the framework place the swap in a frame that has
spare time. Measured behaviour says no: an idle task resolves in ~3 ms in a
plain `test()` but **does not run at all under a pumped `testWidgets`
pipeline**, so gating the upgrade on one hangs the background load in widget
tests. The deeper objection is the same one in production: a busy map is
exactly the situation with no spare frame time, so the upgrade would be
starved precisely when it is most wanted. Don't retry this without new
evidence.

### Phase 2b — convert coordinates on the worker, not the UI isolate *(done)*

**Rejected: the `TrackGeometry` / `Float64List` model this phase originally
specified.** Two measurements killed it. First, the conversion is already
memoized per feature (see the correction under root cause 5), so the
"O(points) on every rebuild" problem it was designed to solve does not exist.
Second, flutter_map's `Polyline` takes a `List<LatLng>`, so typed buffers
would have to be materialised back into exactly that list on the render path
— moving the cost, not removing it. That is a large refactor across the spec
builders, `buildFullTrackResult`, `hitTestMapTap`, `extractSelectedPoints`,
the segment-overlay merge and the on-device cache, for no measured gain.

**What shipped instead**, which is the part of the original idea that
survives contact with the measurements: the decode hop from Phase 1 now
produces the coordinate→LatLng conversion alongside the parse and seeds
`map_geometry_memo.dart`'s cache with the result. Both halves ride back on
one zero-copy hop, and because the coords lists and their converted points
transfer as a single object graph, identity-keyed caching still works across
the isolate boundary. On native platforms the UI isolate therefore never pays
the cold conversion at all.

**Not on web**, where `compute` runs its callback inline on the main thread:
there the conversion is front-loaded into the decode rather than removed from
it. Web's answer is Phase 4's payload reduction, not more `compute` calls —
the same caveat as root cause 7.

*Verified:* after `decodeGeoOffIsolate`, walking every feature through
`memoCoordsToLatLng` performs **zero** conversions (counted, not timed),
against a baseline test showing an unseeded geo pays one per feature.

### Phase 3 — stop the selection path doing geometry work *(partly done)*

The phase as written was: decompose `ProjectNotifier` into independently
listenable facets, then delete `map_panel.dart`'s `_lastX` guard fields as
compensation that is no longer needed.

**Measuring first changed this too.** Instrumenting `build_specs` /
`style_markers` / `all_points` and driving a 100-activity / 500k-point trip
through a real widget pump showed the selection path costing **~24 ms per
selection change** — over the frame budget on its own. But none of it was
notification scope, and none of it was the spec builders: it was
`_cachedAllPoints`, a list of every point in the trip, derived from `geo`
alone and consumed only by the one-shot fit-to-bounds, sitting in the
*selection*-dependent half of `build()`. Every day or activity tap rebuilt it
for nothing.

Moving that one assignment into the geo-dependent half:

| | before | after |
|---|---|---|
| `style_markers` per selection change | 27.2 ms | **0.7 ms** |

Also folded in: `arcMidpoint` now rides the Phase 2b seeding path alongside
the coordinate conversion, and its per-segment `pow(x, 0.5)` became `sqrt(x)`.

**The `_lastX` guards should stay.** They are the reason a selection change
never re-enters the spec builders at all. This document previously called
them "compensation, not architecture" — they are in fact load-bearing, and
deleting them in favour of finer-grained notification would have made the
selection path slower, not faster. Splitting the notifier remains defensible
as a *maintainability* change; it is not a performance one and should not be
sold as one.

*Verified:* across six selection changes the `all_points` span records one
sample; on the previous placement it records seven.

### Phase 3b — decimate on the worker *(done — issue #299)*

`_maybeDecimatePolylines` marshalled every rendered point into
`(double, double)` records on the UI isolate and handed the result to
`compute()`. Only a `compute()`'s **return** value is zero-copy; its argument
is copied. The first real-device report made the cost of that plain:

```
build_specs       n=3  worst=2402.3ms
  decimate_marshal     worst= 788.4ms
```

788 ms of marshalling plus roughly 1.6 s of argument copy — a 2.4 s UI-isolate
stall. And because the camera-idle gate releases the geo swap after at most a
couple of seconds, that stall landed *in the middle of an active pan*, which
is what tripped Android's ANR watchdog on aggressive panning. This is exactly
the failure root cause 3 predicted and Phase 2a did not fix: deferral without
a cheaper rebuild only moves the stall.

The decode hop now produces the decimated geometry itself, using the same
aggregate budget and the same `>= 2 point` filter the spec builder applies, so
the shares come out identical. At most `kMaxTotalPolylinePoints` points come
back, so the return costs nothing. The map looks the result up per feature
instead of marshalling anything.

The async fallback stays for geometry the worker never saw: client-built E2EE
geo, and locally patched segments merged in after a load.

**The on-disk cache was a second door, and it was missed.** The first fix
seeded only geometry that arrived over the network. A trip served from
`projectDataCache`'s L2 — i.e. any open after an app restart — was decoded
straight to a Map, producing fresh coordinate lists that none of the
identity-keyed caches had ever seen, so it paid the entire cold derivation on
the UI isolate. That is the same 2.4 s stall, on the more common path, and it
is why aggressive panning still tripped the ANR watchdog after the first fix
shipped.

The stored blob is `gzip(utf8(jsonEncode(geo)))`, so gunzipping it without
decoding yields precisely the bytes the network path receives. The cache now
returns those bytes and they go through the identical parse-derive-seed hop.
L1 is still preferred when present: that Map is the very object the decode hop
seeded earlier in the session.

The lesson worth keeping: **derived-geometry seeding has to be a property of
where geo enters the app, not of one code path.** Both entry points now share
`ProjectService.readCachedGeo`.

**That fix was itself wrong, in an instructive way.** It skipped the bytes
path whenever L1 already held the ref, on the reasoning that an L1 Map is the
object the decode hop seeded. But `ProjectDataCache._readDisk` promotes an
*entire disk row* into L1, and a load reads low-res geo first — so an
unseeded full geo is already sitting in L1 by the time the check runs, and
the fix never engaged on the path it was written for. Seeding is now asked of
the geometry itself (`geoGeometrySeeded`) instead of inferred from cache
residency. Low-res geo takes the same hop, since on a long trip it is over
the render budget too.

## Measuring the gesture, not just the load

Three rounds of fixes were aimed at load-time work on the strength of
load-time numbers, and the ANR outlived all of them. On a 180-day trip the
device reported a worst blocking span of 102 ms — with Android's watchdog at
~5 s, that is an order of magnitude too small to be the ANR. Every span in
this app measured *loading*; nothing measured the pan.

`PerfSpans` now captures frame build/raster times while the map camera is
moving (driven from `setMapCameraActive`, which all three map screens already
call), and the map records what it hands the renderer each frame:
`rendered_points` and `markers`. Settings → Performance renders live rather
than from the load-end snapshot, so panning and then opening it shows the
gesture.

Those two counts matter because `flutter_map` re-walks every point of every
polyline overlapping the viewport, and repositions every marker, **on every
camera frame**. On a 180-day trip the marker count is the untested suspect:
every memory is a widget holding a network thumbnail, and nothing about that
scales with the viewport.

*Verified:* a widget test asserting the `decimate_marshal` span is **never
recorded** for geo that arrived through the decode hop, that the render budget
is still applied, and that the fallback still runs for geo that did not.

### Phase 4 — server-side level of detail (the long game)

1. **Track tiles for authenticated projects.** Generalise
   `src/tile_renderer.py` beyond share tokens; serve
   `/api/geo/project/tiles/{z}/{x}/{y}.png`. The client renders tiles as the
   base track and fetches full-res vector geometry only for the selection.
   The client plumbing already exists.
2. **Precomputed elevation profile endpoint.** Stop shipping raw per-point
   `elevation_profile` inside the ~12 MB details blob. Serve a
   distance-indexed profile downsampled to ~2000 points — the chart needs
   roughly one point per horizontal pixel. This removes the 12 MB payload,
   its parse, `buildFullTrackResult` and `computeElevationSpots` in one move:
   the entire back half of the load timeline.

*Verify:* the full-res `getDetails` disappears from the cold-open path;
measure payload bytes and time-to-interactive before and after.

**Compatibility note:** 4.2 changes the details payload contract, and there
are Android/iOS builds in the wild. Ship it as a version-gated additional
endpoint, not a breaking change to the existing one.

### Phase 5 — marker layer

Viewport-scoped marker construction, and a single `CustomPainter` layer for
un-selected memory pins instead of N widgets each holding a network
thumbnail. Revisit `MAP_TILE_MODE=raster` with phases 1–3 in place, on real
measurements rather than the currently parked assumption.

## Where this started

Phases 0 and 1 together carry the least architectural risk and address the
largest unguarded main-thread work left in the app. Phase 2's reveal deletion
is the targeted fix for the "small local blocks and unblocks" symptom. Phase
4 is where the ceiling actually lifts.
