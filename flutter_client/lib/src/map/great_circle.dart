/// Dart port of src/models/great_circle.py — SLERP arc on the unit sphere.
library;

import 'dart:math' as math;

import 'package:latlong2/latlong.dart';

/// Returns [nPoints] [LatLng] values along the great-circle arc from
/// (lat1, lon1) to (lat2, lon2) using spherical linear interpolation.
///
/// Falls back to a two-point straight line for coincident or antipodal points.
List<LatLng> greatCirclePoints(
  double lat1Deg,
  double lon1Deg,
  double lat2Deg,
  double lon2Deg, {
  int nPoints = 50,
}) {
  List<double> toEcef(double latD, double lonD) {
    final lat = latD * math.pi / 180;
    final lon = lonD * math.pi / 180;
    return [
      math.cos(lat) * math.cos(lon),
      math.cos(lat) * math.sin(lon),
      math.sin(lat),
    ];
  }

  LatLng toLatLng(double x, double y, double z) {
    final lat = math.asin(z.clamp(-1.0, 1.0)) * 180 / math.pi;
    final lon = math.atan2(y, x) * 180 / math.pi;
    return LatLng(lat, lon);
  }

  final v1 = toEcef(lat1Deg, lon1Deg);
  final v2 = toEcef(lat2Deg, lon2Deg);

  final dot =
      (v1[0] * v2[0] + v1[1] * v2[1] + v1[2] * v2[2]).clamp(-1.0, 1.0);
  final omega = math.acos(dot);

  // Degenerate: coincident or antipodal
  if (omega < 1e-10 || (omega - math.pi).abs() < 1e-10) {
    return [LatLng(lat1Deg, lon1Deg), LatLng(lat2Deg, lon2Deg)];
  }

  final sinOmega = math.sin(omega);
  final points = <LatLng>[];
  for (var i = 0; i < nPoints; i++) {
    final t = i / (nPoints - 1);
    final k1 = math.sin((1.0 - t) * omega) / sinOmega;
    final k2 = math.sin(t * omega) / sinOmega;
    points.add(toLatLng(
      k1 * v1[0] + k2 * v2[0],
      k1 * v1[1] + k2 * v2[1],
      k1 * v1[2] + k2 * v2[2],
    ));
  }
  return points;
}
