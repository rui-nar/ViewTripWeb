/// Per-feature coordinate→LatLng memoization, shared by the map panels and by
/// the decode path that can pre-populate it (issue #293).
///
/// The map rebuilds whenever `geo` is reassigned. Reconstructing markers and
/// polylines re-ran the O(track-points) conversion for *every* feature on
/// *every* rebuild, which dominated build-thread cost and produced load-time
/// map jank.
///
/// This memoizes that work keyed by the **identity** of the raw coordinates
/// list. Only changed features get a new coords list, so unchanged features
/// hit the cache — "rebuild only changed features" with no signature or
/// invalidation bookkeeping, and entries auto-evict when their coords list is
/// GC'd (Expando). Selection- and style-dependent bits (colour, dimming) are
/// cheap and stay recomputed.
///
/// Returned point lists are shared — callers must treat them as read-only.
///
/// Lives in its own file rather than inside `map_panel.dart` so
/// `heavy_decode.dart` can seed it without a UI-layer import. Measured on a
/// 100-activity / 500k-point trip: a cold conversion is ~83 ms of UI-isolate
/// stall, a warm one ~0.1 ms — so what matters is that the *first* conversion
/// after a geo swap never happens on the UI isolate at all. See
/// [seedCoordsLatLng].
library;

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
