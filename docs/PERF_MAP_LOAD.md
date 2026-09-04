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


## The straight-lines report, and what a duration cannot tell you

The first gesture-instrumented run cleared the ANR: 4000 frames across 80
pans, `janky=82/4000`, worst frame 79 ms, and no UI-isolate span over budget.
But the map showed only straight lines, and the report said why once read
carefully:

```
fetch_geo      n=2  total=5119.8ms  worst=5081.5ms
fetch_details  n=2  total=5411.1ms  worst=5367.1ms
```

with no `decode_geo`, no `decode_details`, and no `geo`/`details` payload
notes. Those notes sit on the line immediately after the fetch, so they can
only be skipped if the fetch threw. `n=2` is not two fetches; it is one
failure at ~5 s plus `_loadFullGeoProgressively`'s retry failing fast.

**A span timed in a `finally` is recorded whether the body returned or
threw.** That made a failing fetch and a slow one indistinguishable, which is
the most misleading thing an instrument can do. `PerfSpans.stage` now records
failures separately and the report prints a `FAILURES` section.

### Why the two largest payloads failed

The API container is capped at 768 MB (`docker-compose.yml.example`), and
`api/geo.py`'s payload cache, shared by `/meta`, full details and both geo
variants, was bounded by an **entry count of 200** rather than by bytes.
Entries are whole gzipped project payloads and are nowhere near uniform: a
small trip's `/meta` is tens of KB, while a 180-day trip's details payload
serialises to ~35 MB before compression. Two hundred of those is gigabytes.

Issue #209's third incident was already this failure mode, the container
OOM-killed at ~779 MB with no single request to blame. Here it presented from
the client side instead: for one trip both large requests failed after ~5 s
while smaller payloads on the same project succeeded, and the retry failed
instantly, which is what an OOM-killed container looks like from outside.

The cache is now bounded by the thing that actually runs out, bytes (64 MB),
with the entry cap kept only as a guard against a flood of tiny entries and a
per-entry ceiling so one oversized payload cannot evict everything else.

This is a mitigation, not the cure. The cure is Phase 4.2: stop building a
35 MB payload at all.


## The ANR was never on the Dart isolate

Six rounds of fixes targeted the Dart UI isolate, and the ANR outlived all of
them. The instrument that finally settled it was the event-loop stall
watchdog, by reporting **nothing**: across two device runs, one of which
ANR'd, the Dart event loop was never blocked for more than ~250 ms. Every
blocking span agreed — worst was `all_points` at 7.9 ms, and
`activity_panel_build` did not even appear.

The thing to have questioned much earlier: **an Android ANR is the platform
main thread failing to handle input for 5 s, and Flutter's Dart code does not
run on that thread.** It runs on the engine's UI thread. Instruments that
only watch the Dart isolate can report all-clear through an ANR, and did.

The second run made it sharper still: an ANR with **one** map gesture, zero
frames captured, and no user interaction at all. Not gesture work, not
geometry, not marker count — `rendered_points` and `markers` stayed flat
across every run where behaviour changed drastically.

### What was actually consuming the device

`_MarkerThumbImage` drew each marker with:

```dart
Image.memory(bytes, width: widget.size, height: widget.size, fit: BoxFit.cover)
```

`width`/`height` are **layout** constraints and do not affect decoding.
Without `cacheWidth`/`cacheHeight` Flutter decodes at native resolution, and
`api/memories.py`'s `_THUMB_SIZE` is `(400, 400)`. So every marker held
roughly 400x400x4 = ~640 KB of decoded bitmap to draw a ~30-pixel circle. At
~600 memory markers that is on the order of **375 MB of native memory** —
outside the Dart heap, outside every span in this codebase, and invisible to
the stall watchdog because decoding does not happen on the UI isolate.

Passing `cacheWidth`/`cacheHeight` sized to the display box times the device
pixel ratio takes each decode to roughly 40 KB: about a 16x reduction.

Alongside it, the encoded-bytes cache behind those thumbnails was a
`static final Map<String, Uint8List>` with **no eviction whatsoever** — the
same mistake as the server payload cache, and the reason hiding the memories
layer freed nothing. It is now a `BoundedByteCache` with a byte budget.

`image_cache` and `thumb_bytes` are reported as payload notes so the next
device run measures this rather than inferring it.


## Phase 4 design rationale: reducing the payload without losing the track

Two payloads get conflated, and the distinction is the whole answer.

| | size (180-day trip) | what it is | used for |
|---|---|---|---|
| `geo` | 4.5 MB | GPS coordinates | drawing the track on the map |
| `details` | 33 MB | activity metadata + `elevation_profile` | the elevation chart, and cursor sync |

**Phase 4.2 targets `details`. Track geometry is untouched** — it stays
full-resolution, encoded as Google polylines at ~1 m precision. Shrinking
33 MB costs nothing on the map line, because the map line is not in there.

### Why `details` is 33 MB

`elevation_profile` is an array of `[distance, elevation]` pairs, one per GPS
sample, serialised as JSON text. `[12.345678, 1234.5]` is ~20 bytes to carry
two numbers that fit in 8 bytes binary, or 2-3 as deltas.

Three levers, in increasing order of how much judgement they need:

1. **Encoding — lossless.** Delta + varint (exactly what the polyline encoding
   already does for coordinates). Elevation to 1 m and distance to 1 m is more
   precision than the data actually has. Typically 5-10x smaller with zero
   fidelity change, and it is most of the win.

   The response is already gzipped, so the wire is smaller than 33 MB — but
   the client still materialises 33 MB of JSON into hundreds of MB of Dart
   objects. Binary encoding shrinks the wire *and* the decode *and* the heap.
   The last of those is what matters if the remaining freeze is GC.

2. **Resolution matched to purpose.** The chart is capped at 300 points
   (`_kMaxChartPoints`) and LTTB-downsamples whatever arrives, so megabytes
   are shipped and all but 300 discarded.

   The real caveat: the profile *is* used at higher resolution than 300, for
   the map-to-chart cursor sync. But the cursor maps distance to position, and
   the position comes from `geo`, which stays full-resolution — so the profile
   only needs enough density to resolve distance-to-elevation smoothly. One
   sample per ~25 m loses nothing visible.

3. **On demand.** A coarse whole-trip profile at load; a single activity's
   full profile fetched only when it is selected.

### The coarse tracks are a separate problem, and LOD makes them sharper

Tracks currently look like straight lines because `kMaxTotalPolylinePoints`
(6000) is shared across ~600 activities — roughly 10 points each. That is a
client *render budget*, not a payload limit: the full-resolution geometry is
already on the device.

- **Today:** 6000 points spread over the whole trip regardless of zoom. Zoomed
  into one day, that day still gets ~10 points.
- **Viewport/zoom-aware LOD:** only activities intersecting the viewport get
  budget, at the density the zoom actually resolves. Zoomed into one day, that
  day gets the whole 6000.

Which is the principle behind all of this: **LOD is not "less detail", it is
"detail where you are looking, instead of detail spread so thin it is useless
everywhere."** Server-side track tiles (Phase 4.1) are the same idea taken
further — the basemap already works this way, which is why it stays sharp at
every zoom without downloading the planet.

### Compatibility

Both halves ship as **additional endpoints**; the existing ones are not
touched. `GET /{name}` keeps serving `elevation_profile` inside the full
details payload, so the Android and iOS builds in the wild carry on working
unchanged — there is no version gate and none is needed, because nothing a
shipped client reads has changed shape.

### What already exists, and what that means for the scope

Two things found while building this, both of which shrink the work:

* **A low-res profile is already stored and already served.**
  `Activity.elevation_profile_low_res` (~300 points) lives in its own column,
  and because `/meta` defers `elevation_profile_json`, `ProjectIO._ep_pairs`
  already falls back to it. So `/meta` — 3.4 MB — *already* carries a
  chart-ready profile, and the chart renders from it before the 33 MB details
  payload arrives at all.
* **The 33 MB fetch therefore buys only cursor precision.** Its one remaining
  consumer is `buildFullTrackResult`, which pairs profile samples with geo
  coordinates to build the distance-indexed track behind the map-to-chart
  cursor. And when the profile is shorter than the coordinate list — which is
  exactly the low-res case — that function already takes its haversine
  fallback and derives distances from the geometry instead.

Which raised the question the next slice had to answer honestly: **does the
client need the full-resolution profile at all?**

**It never did — and the reason it appeared to is a bug.**
`buildFullTrackResult` paired `profile[i]` with `coords[i]` whenever there
were at least as many coordinates as profile samples. That is only correct
when the two are index-aligned, i.e. at full GPS resolution. Given a
*downsampled* profile it mapped the entire distance range onto the leading
fraction of the geometry: measured on a straight 10 km track with a 10-sample
profile, the track ended at lat 0.009 instead of 0.099 — the map cursor
pointing about a tenth of the way along.

So the low-res profile `/meta` already ships could not be used, and the 33 MB
payload existed to paper over that. The builder now always derives distances
from the geometry and scales them to the profile's total (what
`buildTrackFromPolyline` already did as a "fallback"), which needs exactly
*one* number from the profile at any resolution. Cursor accuracy follows the
geometry, which was never the limiting factor.

With that fixed, the client fetches `/elevation` instead of the details
payload, and the 33 MB, its ~9 s fetch, its ~5 s decode and its retention all
go together. E2EE trips still take the old path: their profiles are opaque
envelopes the endpoint cannot open.

One consequence worth recording: the work is now O(geometry coordinates)
rather than O(profile samples), so `_buildFullTrack`'s inline-vs-isolate
threshold had to start measuring coordinates. Gating on profile size alone
would have let a trip carrying the 300-point low-res profile walk hundreds of
thousands of coordinates on the UI isolate — precisely the pattern that guard
exists to prevent.


## Measured: the compact endpoint, and the fetch it did not remove

First device run with the compact path live:

| | before | after |
|---|---|---|
| elevation payload | 33.0 MB | **2.8 MB** |
| decode | 4884 ms | **57 ms** |

But `fetch_details` was *still there*, at 14.1 s. **View mode ran its own
Phase 2**, fetching the full details payload for elevation, entirely
independently of the inherited background upgrade — so a view-mode load
fetched elevation twice: once cheaply through the new endpoint, and once
expensively through the old one.

That Phase 2 predates the low-res profile now carried by `/meta` and the
compact endpoint, and both of the things it existed to do are now done
elsewhere. It is gone, along with the `_ViewProjectService.fetchFullDetails`
that only it called.

Worth recording as a pattern: the report named the problem in one line, but
only because `fetch_elevation` and `fetch_details` appear as *separate* spans.
Aggregate load time would have shown an improvement and hidden a duplicated
14-second fetch completely.

**Shared mode still has the equivalent Phase 2.** Its service talks to
`/api/share/{token}` and there is no share-scoped elevation endpoint yet, so
it keeps fetching the full payload; the compact endpoint 404s there and falls
back. That is the next thing to close.

## Device profiling: what 1.5 GB actually was

Five `dumpsys meminfo` captures over ~7 minutes settled a question three
rounds of inference had not.

| | A | B | C | D | E |
|---|---|---|---|---|---|
| Dart heap (`Unknown`) | 505 | 804 | 622 | 627 | 625 MB |
| `GL mtrack` | 102 | 250 | 273 | 265 | 234 MB |
| Native heap | 49 | 61 | 63 | 72 | 52 MB |
| TOTAL PSS | 798 | 1235 | 1079 | 1085 | 1037 MB |

**Nothing leaks.** Graphics fills a bounded cache and then declines; the
native heap does the same. The app reaches a stable ~1.04 GB PSS.

Two readings along the way were wrong, and both came from too few samples: at
three rising points graphics looked unbounded, and it is not. Four points was
the minimum that distinguished a filling cache from a leak.

`Unknown` is the Dart heap — it *shrank* 169 MB between captures, which fixed
mappings do not do. The Dart VM allocates through anonymous `mmap`, so
`dumpsys` cannot attribute it; it never appears under `Native Heap` (malloc,
and only ~50 MB here).

So the budget is: **Dart heap ~625 MB steady and ~804 MB during load**,
graphics ~320 MB at its plateau, everything else ~120 MB. The Dart heap is
both the largest component and the one that spikes, and GC over a heap that
size is what produces the multi-second frames. Graphics is map surfaces and
is not reducible.

That rules out raster track tiles (Phase 4.1) outright: they would move
geometry out of the Dart heap and into the one pool already at its ceiling.
Zoom level of detail on vector geometry is the answer instead.

## Phase 4.1 replaced: zoom level of detail

`GET /api/geo/project/simplified?name=…&zoom=…` returns geometry
Ramer-Douglas-Peucker-simplified to about one screen pixel at that zoom. The
client holds what it asks for, so the size of the client's geometry becomes a
function of what is on screen rather than of trip length.

The algorithm is the one already used to trim MOTIS shape points, moved to
`src/models/simplify.py` and shared — including its equirectangular
correction, which matters here for the same reason it mattered there: a
degree of longitude is ~63% of a degree of latitude at European latitudes, so
an unprojected epsilon over-simplifies north-south.

Additional endpoint; `/project` is unchanged, for shipped clients and for
anything that genuinely needs every point (track editing, export).

Still to do: a bounding box. Zoom alone bounds the *detail*, not the extent,
so a deep zoom still returns the whole trip at that detail. That is the
follow-up, and it is what makes the high-zoom case bounded too.