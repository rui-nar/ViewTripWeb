/// Google-encoded polyline decoder and distance-indexed track builder.
library;

import 'package:latlong2/latlong.dart';

/// Decode a Google-encoded polyline string to a list of [LatLng] points.
List<LatLng> decodePolyline(String encoded) {
  final result = <LatLng>[];
  int index = 0, lat = 0, lng = 0;
  while (index < encoded.length) {
    int b, shift = 0, r = 0;
    do {
      b = encoded.codeUnitAt(index++) - 63;
      r |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    lat += (r & 1) != 0 ? ~(r >> 1) : (r >> 1);
    shift = 0;
    r = 0;
    do {
      b = encoded.codeUnitAt(index++) - 63;
      r |= (b & 0x1f) << shift;
      shift += 5;
    } while (b >= 0x20);
    lng += (r & 1) != 0 ? ~(r >> 1) : (r >> 1);
    result.add(LatLng(lat / 1e5, lng / 1e5));
  }
  return result;
}

/// Interpolate a [LatLng] from a distance-indexed track at [distKm].
///
/// [track] is a list of `(cumulativeDistanceKm, LatLng)` records sorted by
/// distance, as built by [ElevationChart._compute] from the activity's
/// elevation profile and decoded polyline.
LatLng? latLonAtDistance(List<(double, LatLng)> track, double distKm) {
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
  return LatLng(
    a.latitude  + t * (b.latitude  - a.latitude),
    a.longitude + t * (b.longitude - a.longitude),
  );
}
