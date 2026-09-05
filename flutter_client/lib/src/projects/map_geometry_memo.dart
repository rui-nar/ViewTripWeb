/// Per-feature coordinate→LatLng memoization, shared by the map panels and by
/// the decode path that can pre-populate it (issue #293).
///
/// The map rebuilds whenever `geo` is reassigned. Reconstructing markers and
/// polylines re-ran the O(track-points) conversion for *every* feature on
/// *every* rebuild, which dominated build-thread cost and produced load-time
/// map jank.
///
/// It also holds the trip's other per-feature geometry derivations — the arc
/// midpoint, the decimated render geometry, and the flattened track
/// coordinates — all keyed the same way and all producible on a worker.
///
/// This memoizes that work keyed by the **identity** of the raw coordinates
/// list. Only changed features get a new coords list, so unchanged features
/// hit the cache — "rebuild only changed features" with no signature or
/// invalidation bookkeeping, and entries auto-evict when their coords list is
/// GC'd (Expando). Selection- and style-dependent bits (colour, dimming) are
/// cheap and stay recomputed.
///
/// Returned point lists and coordinate buffers are shared — callers must
/// treat them as read-only.
///
/// Lives in its own file rather than inside `map_panel.dart` so
/// `heavy_decode.dart` can seed it without a UI-layer import. Measured on a
/// 100-activity / 500k-point trip: a cold conversion is ~83 ms of UI-isolate
/// stall, a warm one ~0.1 ms — so what matters is that the *first* conversion
/// after a geo swap never happens on the UI isolate at all. See
/// [seedCoordsLatLng].
library;

import 'dart:math' show sqrt;
import 'dart:typed_data';

import 'package:flutter/foundation.dart' show visibleForTesting;
import 'package:latlong2/latlong.dart';

final Expando<List<LatLng>> _coordsLatLngCache = Expando('coordsLatLng');

/// How many conversions [memoCoordsToLatLng] has actually performed (cache
/// misses). Exists so a test can assert a pre-seeded cache does *zero* work,
/// rather than inferring it from a wall clock.
@visibleForTesting
int coordsConversionCount = 0;

List<LatLng> memoCoordsToLatLng(List coords) {
  final cached = _coordsLatLngCache[coords];
  if (cached != null) return cached;
  coordsConversionCount++;
  final pts = coordsToLatLng(coords);
  _coordsLatLngCache[coords] = pts;
  return pts;
}

/// The conversion [memoCoordsToLatLng] memoizes, without the cache. Pure, so
/// it can run on a worker isolate — GeoJSON coordinates are `[lon, lat]`,
/// [LatLng] is `(lat, lon)`. Malformed entries are skipped rather than thrown
/// on: a single bad pair must not take out a whole trip's track.
List<LatLng> coordsToLatLng(List coords) {
  final pts = <LatLng>[];
  for (final c in coords) {
    if (c is List && c.length >= 2) {
      pts.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
    }
  }
  return pts;
}

/// Records [points] as the conversion of [coords], so the first map build
/// after a geo swap finds the cache already warm.
///
/// Used by `heavy_decode.dart`: the isolate that parses a geo payload also
/// converts it, and the result rides back on the same zero-copy hop, so the
/// UI isolate never pays the cold conversion. Keying still works across the
/// isolate boundary because the coords lists and the point lists are
/// transferred as one object graph, preserving identity between them.
void seedCoordsLatLng(List coords, List<LatLng> points) {
  _coordsLatLngCache[coords] = points;
}

// ── Arc midpoint ─────────────────────────────────────────────────────────────

final Expando<LatLng> _arcMidpointCache = Expando('arcMidpoint');

/// Midpoint of [coords], memoized on the coords list's identity — the label
/// anchor for an activity's track. Cold cost is O(points) with a square root
/// per segment, so like the coordinate conversion above it is worth producing
/// on a worker and seeding rather than paying on the UI isolate.
LatLng? memoArcMidpoint(List coords) {
  final cached = _arcMidpointCache[coords];
  if (cached != null) return cached;
  final m = arcMidpoint(coords);
  if (m != null) _arcMidpointCache[coords] = m;
  return m;
}

final Expando<List<LatLng>> _decimatedCache = Expando('decimatedLatLng');

/// The decimated render geometry for [coords], or null if the decode hop did
/// not produce one (client-built geo, locally patched segments).
List<LatLng>? decimatedLatLng(List coords) => _decimatedCache[coords];

/// Records [points] as the decimated render geometry of [coords] — see
/// polyline_decimation.dart for why this is produced on the worker.
void seedDecimatedLatLng(List coords, List<LatLng> points) {
  _decimatedCache[coords] = points;
}

/// Whether [geo]'s drawable geometry has already been derived and seeded.
///
/// Asked of the geometry itself rather than inferred from where the Map came
/// from: `ProjectDataCache._readDisk` promotes a whole disk row into L1, so
/// "L1 holds this ref" does NOT imply "the decode hop seeded it" — a load
/// reads low-res geo first, which pulls the row in, and an unseeded full geo
/// rides along with it. Inferring seeding from cache residency is what made
/// the first attempt at this fix a no-op on the exact path it targeted.
bool geoGeometrySeeded(Map<String, dynamic> geo) {
  final features = geo['features'];
  if (features is! List) return true; // nothing to draw, nothing to derive
  for (final f in features) {
    if (f is! Map) continue;
    final coords = (f['geometry'] as Map? ?? {})['coordinates'];
    if (coords is! List || coords.length < 2) continue;
    return _decimatedCache[coords] != null;
  }
  return true; // no drawable feature
}

/// Records [midpoint] as the arc midpoint of [coords]. See [seedCoordsLatLng].
void seedArcMidpoint(List coords, LatLng midpoint) {
  _arcMidpointCache[coords] = midpoint;
}

/// Returns the coordinate at 50% of the total chord length — accurate even
/// when points are unevenly spaced (e.g. resolved rail/ferry/bus routes).
LatLng? arcMidpoint(List coords) {
  if (coords.isEmpty) return null;
  if (coords.length == 1) {
    final c = coords[0];
    if (c is! List || c.length < 2) return null;
    return LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble());
  }
  double total = 0;
  final lens = <double>[0.0];
  for (int i = 1; i < coords.length; i++) {
    final a = coords[i - 1], b = coords[i];
    if (a is! List || b is! List || a.length < 2 || b.length < 2) {
      lens.add(total);
      continue;
    }
    final dlat = (b[1] as num).toDouble() - (a[1] as num).toDouble();
    final dlon = (b[0] as num).toDouble() - (a[0] as num).toDouble();
    total += sqrt(dlat * dlat + dlon * dlon);
    lens.add(total);
  }
  final half = total / 2;
  for (int i = 1; i < lens.length; i++) {
    if (lens[i] >= half) {
      final t = (lens[i] - lens[i - 1]) == 0
          ? 0.0
          : (half - lens[i - 1]) / (lens[i] - lens[i - 1]);
      final a = coords[i - 1], b = coords[i];
      if (a is! List || b is! List || a.length < 2 || b.length < 2) break;
      return LatLng(
        (a[1] as num).toDouble() + t * ((b[1] as num).toDouble() - (a[1] as num).toDouble()),
        (a[0] as num).toDouble() + t * ((b[0] as num).toDouble() - (a[0] as num).toDouble()),
      );
    }
  }
  final last = coords.last;
  if (last is! List || last.length < 2) return null;
  return LatLng((last[1] as num).toDouble(), (last[0] as num).toDouble());
}

// ── Flat track coordinates ──────────────────────────────────────────────────

final Expando<Float64List> _flatCoordsCache = Expando('flatCoords');

/// How many flattenings [memoFlatCoords] has actually performed (cache
/// misses). Mirrors [coordsConversionCount], and exists for the same reason:
/// so a test can assert a pre-seeded cache does *zero* work.
@visibleForTesting
int flatCoordsConversionCount = 0;

/// The activity id and raw coordinate list [feature] contributes to the trip's
/// distance-indexed track, or null if it contributes nothing.
///
/// The single definition of which features that track is built from — non-Map
/// entries, segments, features carrying no `activity_id` and features with no
/// coordinates all contribute nothing. Shared so that the worker deciding
/// what to flatten and the UI isolate deciding what to look up cannot drift
/// apart: a worker that skipped a feature the builder wants would only cost a
/// cache miss, but a worker that flattened one the builder ignores would
/// retain a buffer nothing ever reads. Returning the coords list as well as
/// the id means both sides key on the same object rather than re-deriving it.
({String activityId, List coords})? trackFeatureCoords(Object? feature) {
  if (feature is! Map) return null;
  final props = feature['properties'] as Map? ?? {};
  if (props['type'] == 'segment') return null;
  final actId = props['activity_id']?.toString();
  if (actId == null) return null;
  final coords = (feature['geometry'] as Map? ?? {})['coordinates'];
  if (coords is! List || coords.isEmpty) return null;
  return (activityId: actId, coords: coords);
}

/// [flatCoords] for [coords], memoized on the coords list's identity.
///
/// The miss path is what issue #337 is about: it is O(points) on whichever
/// isolate calls it, and on the UI isolate a real trip measured 22.6 ms of it
/// — the only span left over the frame budget. `heavy_decode.dart` produces
/// this on the decode worker and [seedFlatCoords]s it, so the UI isolate hits
/// the cache instead. A miss is still correct, just slower: geometry that
/// never went through that decode (client-built E2EE geo, a locally patched
/// feature) flattens here on demand.
Float64List memoFlatCoords(List coords) {
  final cached = _flatCoordsCache[coords];
  if (cached != null) return cached;
  flatCoordsConversionCount++;
  final flat = flatCoords(coords);
  _flatCoordsCache[coords] = flat;
  return flat;
}

/// GeoJSON [coords] interleaved into one `[lon, lat, lon, lat, …]` buffer.
///
/// Typed data crosses an isolate boundary as a buffer rather than object by
/// object, which is why the track builder takes this shape — see
/// `FlatGeoCoords` in project_notifier.dart. Pure, so it can run on a worker.
/// Entries that are not a pair are skipped rather than thrown on, exactly as
/// [coordsToLatLng] skips them.
Float64List flatCoords(List coords) {
  final buf = Float64List(coords.length * 2);
  var n = 0;
  for (final c in coords) {
    if (c is! List || c.length < 2) continue;
    buf[n++] = (c[0] as num).toDouble();
    buf[n++] = (c[1] as num).toDouble();
  }
  return n == buf.length ? buf : buf.sublist(0, n);
}

/// Records [flat] as the flattening of [coords]. See [seedCoordsLatLng].
void seedFlatCoords(List coords, Float64List flat) {
  _flatCoordsCache[coords] = flat;
}
