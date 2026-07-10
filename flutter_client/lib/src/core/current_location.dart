/// Best-effort device location for the encounter location picker (#40).
library;

import 'package:geolocator/geolocator.dart';
import 'package:latlong2/latlong.dart';

/// Return the device's current position, or null if location services are off,
/// permission is denied, or the fix times out. Never throws — callers fall back
/// to letting the user place the pin manually.
Future<LatLng?> currentDeviceLatLng() async {
  try {
    if (!await Geolocator.isLocationServiceEnabled()) return null;
    var perm = await Geolocator.checkPermission();
    if (perm == LocationPermission.denied) {
      perm = await Geolocator.requestPermission();
    }
    if (perm == LocationPermission.denied ||
        perm == LocationPermission.deniedForever) {
      return null;
    }
    final pos = await Geolocator.getCurrentPosition(
      locationSettings: const LocationSettings(
        accuracy: LocationAccuracy.medium,
        timeLimit: Duration(seconds: 8),
      ),
    );
    return LatLng(pos.latitude, pos.longitude);
  } catch (_) {
    return null;
  }
}
