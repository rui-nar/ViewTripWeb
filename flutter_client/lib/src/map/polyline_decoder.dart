/// Google-encoded polyline decoder and distance-indexed track builder.
library;

import 'dart:math' as math;

import 'geo_point.dart';

/// Decode a Google-encoded polyline string to a list of [GeoPoint] values.
///
/// Web-safe: avoids `<<`, `|`, `>>` and `~` on accumulated values. When Dart is
/// compiled to JavaScript, bitwise/shift operators run as 32-bit ops and `~`
/// returns an *unsigned* complement (`4294967295 - x`) rather than the VM's
/// signed `-x - 1`. The classic decoder (`r |= (b & 0x1f) << shift;` then
/// `~(r >> 1)`) therefore turned every negative delta into a ~4.29e9 value on
/// the web, accumulating into out-of-range coordinates (a latitude of ~42e6
/// that crashed flutter_map's bounds assertion). Using multiplication for the
/// shift, addition for the OR (the 5-bit groups never overlap), and integer
/// division for the zig-zag keeps the maths exact and identical on the VM,
/// dart2js and DDC. See https://dart.dev/resources/language/number-representation
List<GeoPoint> decodePolyline(String encoded) {
  final result = <GeoPoint>[];
  int index = 0, lat = 0, lng = 0;

  int readDelta() {
    int shift = 0, r = 0, b;
    do {
      b = encoded.codeUnitAt(index++) - 63;
      r += (b & 0x1f) * (1 << shift); // shift ≤ 25 here, so 1<<shift fits 32 bits
      shift += 5;
    } while (b >= 0x20);
    // Zig-zag inverse without ~ or >> on a possibly-large value.
    return (r & 1) != 0 ? -((r + 1) ~/ 2) : (r ~/ 2);
  }

  while (index < encoded.length) {
    lat += readDelta();
    lng += readDelta();
    result.add((lat: lat / 1e5, lon: lng / 1e5));
  }
  return result;
}

/// Build a distance-indexed track from decoded [points] using haversine geometry.
///
/// Used as a fallback when the stored polyline is shorter than the elevation
/// profile (e.g. desktop-migrated activities that still carry the compressed
/// Strava summary polyline). Distances are scaled so the last point matches
/// [elevTotalKm], keeping the track aligned with the elevation chart's x-axis.
///
/// [offsetKm] is added to every distance (used to chain multiple activities).
List<(double, GeoPoint)> buildTrackFromPolyline(
  List<GeoPoint> points, {
  double elevTotalKm = 0,
  double offsetKm = 0,
}) {
  if (points.isEmpty) return const [];
  final track = <(double, GeoPoint)>[];
  double cumDist = 0;
  track.add((0, points.first));
  for (int i = 1; i < points.length; i++) {
    cumDist += _haversineKm(points[i - 1], points[i]);
    track.add((cumDist, points[i]));
  }
  final scale =
      (cumDist > 0 && elevTotalKm > 0) ? elevTotalKm / cumDist : 1.0;
  return [
    for (final pt in track) (offsetKm + pt.$1 * scale, pt.$2),
  ];
}

double _haversineKm(GeoPoint a, GeoPoint b) {
  const r = 6371.0;
  final dLat = (b.lat - a.lat) * (math.pi / 180);
  final dLon = (b.lon - a.lon) * (math.pi / 180);
  final sinDLat = math.sin(dLat / 2);
  final sinDLon = math.sin(dLon / 2);
  final h = (sinDLat * sinDLat +
          math.cos(a.lat * math.pi / 180) *
              math.cos(b.lat * math.pi / 180) *
              sinDLon * sinDLon)
      .clamp(0.0, 1.0);
  return 2 * r * math.asin(math.sqrt(h));
}

/// Interpolate a [GeoPoint] from a distance-indexed track at [distKm].
///
/// [track] is a list of `(cumulativeDistanceKm, GeoPoint)` records sorted by
/// distance, as built by [ElevationChart._compute].
GeoPoint? latLonAtDistance(List<(double, GeoPoint)> track, double distKm) {
  if (track.isEmpty) return null;
  if (distKm <= track.first.$1) return track.first.$2;
  if (distKm >= track.last.$1) return track.last.$2;
  int lo = 0, hi = track.length - 1;
  while (lo + 1 < hi) {
    final mid = (lo + hi) ~/ 2;
    if (track[mid].$1 <= distKm) { lo = mid; } else { hi = mid; }
  }
  final span = track[hi].$1 - track[lo].$1;
  if (span == 0) return track[lo].$2;
  final t = (distKm - track[lo].$1) / span;
  final a = track[lo].$2;
  final b = track[hi].$2;
  return (
    lat: a.lat + t * (b.lat - a.lat),
    lon: a.lon + t * (b.lon - a.lon),
  );
}
