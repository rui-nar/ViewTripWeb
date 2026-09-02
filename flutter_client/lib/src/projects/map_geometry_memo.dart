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

import 'dart:math' show sqrt;

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

