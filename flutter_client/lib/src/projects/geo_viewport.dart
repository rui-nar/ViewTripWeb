/// The viewport box the client asks the server for — issue #324.
///
/// Zoom bounds the *detail* of the geometry the server sends; it does nothing
/// about the *extent*. At zoom 15 a long trip is almost entirely off screen and
/// was still being simplified in full on every request — measured at 4.0 s of
/// server CPU for a 219-activity trip, against 0.26 s at zoom 9. The cost rises
/// with zoom while the saving falls (issue #324). Scoping the request to what
/// is on screen is what makes the deep-zoom case bounded in both directions.
///
/// Pure Web Mercator arithmetic and no flutter_map import, so the snapping and
/// the refetch trigger are testable without a map. It mirrors
/// `snap_bbox_to_tiles` in `src/models/simplify.py`; the server snaps again on
/// arrival rather than trusting this, so the two drifting apart costs a cache
/// miss and never correctness.
library;

import 'dart:math' as math;

/// Web Mercator cannot represent the poles; the standard tile grid stops here.
const double _kMaxMercatorLat = 85.05112878;

/// A longitude/latitude box, in the order the `bbox` query parameter takes.
class GeoBox {
  const GeoBox(this.west, this.south, this.east, this.north);

  final double west, south, east, north;

  /// Whether [other] lies entirely within this box. This is the refetch
  /// trigger: while the camera stays inside the box that was fetched, the
  /// geometry on screen is already the right geometry.
  bool contains(GeoBox other) =>
      other.west >= west &&
      other.east <= east &&
      other.south >= south &&
      other.north <= north;

  /// `minLon,minLat,maxLon,maxLat`, six decimals — about 10 cm, far finer than
  /// the tile grid this is snapped to, and a fixed length so the string that
  /// keys the in-flight-request dedup is stable.
  String get param => '${west.toStringAsFixed(6)},${south.toStringAsFixed(6)},'
      '${east.toStringAsFixed(6)},${north.toStringAsFixed(6)}';

  @override
  bool operator ==(Object other) =>
      other is GeoBox &&
      other.west == west &&
      other.south == south &&
      other.east == east &&
      other.north == north;

  @override
  int get hashCode => Object.hash(west, south, east, north);

  @override
  String toString() => 'GeoBox($param)';
}

/// The map camera's visible bounds as a [GeoBox], or null when they cannot be
/// used as one.
///
/// Null for a box that crosses the antimeridian (west >= east), for a
/// degenerate one, and for anything non-finite — flutter_map can report an
/// unwrapped or empty camera before the map has been laid out. Null means "ask
/// for the whole trip", which is exactly what the code did before this
/// existed, so every one of those cases degrades to the previous behaviour
/// rather than to a wrong box.
GeoBox? viewportBox(double west, double south, double east, double north) {
  for (final v in [west, south, east, north]) {
    if (!v.isFinite) return null;
  }
  if (west >= east || south >= north) return null;
  if (west < -180 || east > 180 || south < -90 || north > 90) return null;
  // Clamped to what Web Mercator can represent, before anything compares
  // against it. A camera zoomed far out reports latitudes past 85.05, and no
  // tile-aligned box can ever cover those — so an unclamped viewport is one
  // [fetchBoxFor] cannot satisfy, and `_geoIsStaleForCamera` would then stay
  // true forever (issue #332). Clamping here means every GeoBox that reaches
  // the refetch trigger is one a box can actually contain.
  final s = south.clamp(-_kMaxMercatorLat, _kMaxMercatorLat);
  final n = north.clamp(-_kMaxMercatorLat, _kMaxMercatorLat);
  // Both ends past the limit collapse to the same latitude. Degenerate is not
  // a box; null means "ask for the whole trip", the pre-scoping behaviour.
  if (s >= n) return null;
  return GeoBox(west, s, east, n);
}

double _lonToTileX(double lon, int n) => (lon + 180.0) / 360.0 * n;

double _latToTileY(double lat, int n) {
  final clamped = lat.clamp(-_kMaxMercatorLat, _kMaxMercatorLat);
  final r = clamped * math.pi / 180.0;
  return (1.0 - math.log(math.tan(r) + 1.0 / math.cos(r)) / math.pi) / 2.0 * n;
}

double _tileXToLon(int x, int n) => x / n * 360.0 - 180.0;

double _tileYToLat(int y, int n) {
  final t = math.pi * (1.0 - 2.0 * y / n);
  return math.atan((math.exp(t) - math.exp(-t)) / 2.0) * 180.0 / math.pi;
}

/// The box to actually fetch for [viewport] at [level]: padded, then snapped
/// outward to whole Web Mercator tiles.
///
/// Two jobs, and they are the same mechanism seen twice:
///
/// * **Padding.** A pan of a few pixels must not go back to the server. The
///   viewport is grown by [padFraction] of its own size on each side, and
///   snapping then adds up to another tile.
/// * **Bounded cache keys.** Raw viewport floats mean a distinct server cache
///   entry per pan pixel. This project has already OOM-killed its API container
///   once with a payload cache bounded by the wrong thing (issue #209's third
///   incident, and again from the client side in #276), so the box is snapped
///   to the grid the zoom already defines and neighbouring viewports reuse one
///   entry. The server snaps whatever it receives as well, because an older or
///   hostile client must not be able to mint entries either.
///
/// Snapping is outward, never inward: the answer must be a superset of what is
/// on screen or the map draws a gap at the edge.
///
/// **Postcondition: `fetchBoxFor(v, level).contains(v)` for every `v`.** That
/// is not a nicety — it is the entire contract with [GeoBox.contains], which
/// `ProjectNotifier._geoIsStaleForCamera` uses as its refetch trigger. It did
/// not hold, and nothing tested it: the padded latitudes are clamped to +/-90
/// while [_latToTileY] clamps to the Mercator limit of +/-85.05, so a viewport
/// reaching past 85 got back a box stopping at 85.05 — a box that could not
/// contain the viewport it was built from. The camera was then permanently
/// stale, every camera event scheduled another refetch, and each refetch
/// copied the trip's geometry into an isolate: 2.6 GB of Dart heap and an ANR
/// on device (issue #332). See the pole handling below and the property test
/// in geo_viewport_test.dart.
GeoBox fetchBoxFor(GeoBox viewport, int level, {double padFraction = 0.25}) {
  final n = 1 << level.clamp(0, 22);
  final padX = (viewport.east - viewport.west) * padFraction;
  final padY = (viewport.north - viewport.south) * padFraction;
  final west = (viewport.west - padX).clamp(-180.0, 180.0);
  final east = (viewport.east + padX).clamp(-180.0, 180.0);
  final south = (viewport.south - padY).clamp(-90.0, 90.0);
  final north = (viewport.north + padY).clamp(-90.0, 90.0);

  var x0 = _lonToTileX(west, n).floor().clamp(0, n);
  var x1 = _lonToTileX(east, n).ceil().clamp(0, n);
  // Tile y grows southward, so the box's max latitude is its min y.
  var y0 = _latToTileY(north, n).floor().clamp(0, n);
  var y1 = _latToTileY(south, n).ceil().clamp(0, n);
  // A viewport thinner than a tile lands on one boundary twice; widen it to a
  // whole tile so the box is never empty.
  if (x1 == x0) {
    x1 = math.min(n, x0 + 1);
    x0 = x1 - 1;
  }
  if (y1 == y0) {
    y1 = math.min(n, y0 + 1);
    y0 = y1 - 1;
  }
  // Widened to cover the viewport unconditionally. Snapping outward should
  // already guarantee this, and the property test asserts it — but the
  // postcondition is what the refetch loop's termination depends on, so it is
  // enforced here rather than argued for. A float edge at a tile boundary, or
  // a later change to the projection helpers, then costs a slightly larger box
  // instead of an app that cannot stop fetching. The server re-snaps whatever
  // it receives, so its cache keys stay bounded either way.
  return GeoBox(
    math.min(_tileXToLon(x0, n), viewport.west),
    math.min(_tileYToLat(y1, n), viewport.south),
    math.max(_tileXToLon(x1, n), viewport.east),
    math.max(_tileYToLat(y0, n), viewport.north),
  );
}
