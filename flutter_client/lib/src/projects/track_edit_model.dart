/// Pure, UI-independent edit model for the activity track editor (issue #31).
///
/// Holds the canonical ordered point list and the geometry-only edit operations
/// the editor page drives — trim, add, remove, split — plus dirty tracking and
/// the JSON save payload for `PUT /api/projects/{name}/activities/{id}/track`.
///
/// Keeping this logic free of Flutter widgets makes every edit operation and the
/// produced save payload directly unit-testable (per the plan's Phase-3 tests),
/// and lets the page stay a thin rendering + gesture layer on top.
library;

import '../map/polyline_decoder.dart';
import '../map/geo_point.dart';

/// One editable track vertex: position plus optional elevation (metres).
class EditPoint {
  final double lat;
  final double lng;
  final double? elev;

  const EditPoint(this.lat, this.lng, [this.elev]);

  GeoPoint get geo => (lat: lat, lon: lng);

  Map<String, dynamic> toJson() => {
        'lat': lat,
        'lng': lng,
        if (elev != null) 'elev': elev,
      };

  @override
  bool operator ==(Object other) =>
      other is EditPoint &&
      other.lat == lat &&
      other.lng == lng &&
      other.elev == elev;

  @override
  int get hashCode => Object.hash(lat, lng, elev);
}

/// Mutable edit state for a single activity's track.
///
/// Construct via [TrackEditModel.fromEncoded] with the stored polyline and the
/// elevation profile pairs (`[[distKm, elevM], …]`) so elevation is aligned onto
/// the decoded polyline points by cumulative distance — mirroring the server's
/// canonical representation.
class TrackEditModel {
  final List<EditPoint> _points;
  final List<EditPoint> _original;

  TrackEditModel._(this._points)
      : _original = List<EditPoint>.unmodifiable(_points);

  /// Build from a Google-encoded [polyline] and optional [elevationPairs]
  /// (`[[distanceKm, elevationM], …]`). Elevation is interpolated onto the
  /// decoded points by cumulative haversine distance.
  factory TrackEditModel.fromEncoded(
    String? polyline,
    List<List<double>>? elevationPairs,
  ) {
    final decoded = (polyline == null || polyline.isEmpty)
        ? const <GeoPoint>[]
        : decodePolyline(polyline);
    if (decoded.isEmpty) return TrackEditModel._(<EditPoint>[]);

    if (elevationPairs == null || elevationPairs.isEmpty) {
      return TrackEditModel._(
        [for (final p in decoded) EditPoint(p.lat, p.lon)],
      );
    }

    // Cumulative distance along the decoded polyline, then interpolate elevation.
    final track = buildTrackFromPolyline(decoded);
    final dist = [for (final e in elevationPairs) e[0]];
    final elev = [for (final e in elevationPairs) e[1]];
    return TrackEditModel._([
      for (final entry in track)
        EditPoint(entry.$2.lat, entry.$2.lon, _interp(entry.$1, dist, elev)),
    ]);
  }

  /// Test/seam constructor from an explicit point list.
  factory TrackEditModel.fromPoints(List<EditPoint> points) =>
      TrackEditModel._(List<EditPoint>.of(points));

  List<EditPoint> get points => List<EditPoint>.unmodifiable(_points);
  int get length => _points.length;

  /// True when the current points differ from the loaded originals.
  bool get isDirty {
    if (_points.length != _original.length) return true;
    for (var i = 0; i < _points.length; i++) {
      if (_points[i] != _original[i]) return true;
    }
    return false;
  }

  /// A valid track needs at least two points (matches the server's guard).
  bool get isValid => _points.length >= 2;

  // ── Edit operations ─────────────────────────────────────────────────────

  /// Trim to the inclusive index range [start]..[end], dropping points outside.
  void trim(int start, int end) {
    if (start < 0 || end >= _points.length || start > end) {
      throw RangeError('trim($start, $end) out of range for ${_points.length}');
    }
    final kept = _points.sublist(start, end + 1);
    _points
      ..clear()
      ..addAll(kept);
  }

  /// Insert [point] after the vertex at [index] (i.e. into the segment
  /// starting at [index]). Use index = -1 to prepend.
  void addPointAfter(int index, EditPoint point) {
    if (index < -1 || index >= _points.length) {
      throw RangeError('addPointAfter($index) out of range');
    }
    _points.insert(index + 1, point);
  }

  /// Remove the vertex at [index].
  void removePoint(int index) {
    if (index < 0 || index >= _points.length) {
      throw RangeError('removePoint($index) out of range');
    }
    _points.removeAt(index);
  }

  /// Move the vertex at [index] to a new position (drag-end handle / reshape).
  void movePoint(int index, double lat, double lng) {
    if (index < 0 || index >= _points.length) {
      throw RangeError('movePoint($index) out of range');
    }
    final old = _points[index];
    _points[index] = EditPoint(lat, lng, old.elev);
  }

  /// Return the head/tail point lists for a split at [index] (the boundary point
  /// is shared: head = [0..index], tail = [index..end]). Does not mutate state —
  /// splitting is a server operation; this only validates and previews.
  ({List<EditPoint> head, List<EditPoint> tail}) previewSplit(int index) {
    if (index < 1 || index > _points.length - 2) {
      throw RangeError('previewSplit($index) needs two non-trivial pieces');
    }
    return (
      head: _points.sublist(0, index + 1),
      tail: _points.sublist(index),
    );
  }

  // ── Save payload ─────────────────────────────────────────────────────────

  /// The `{points: [...]}` body for the track PUT endpoint.
  Map<String, dynamic> toSavePayload() => {
        'points': [for (final p in _points) p.toJson()],
      };

  static double _interp(double d, List<double> dist, List<double> elev) {
    if (dist.isEmpty) return 0;
    if (d <= dist.first) return elev.first;
    if (d >= dist.last) return elev.last;
    for (var i = 1; i < dist.length; i++) {
      if (d <= dist[i]) {
        final d0 = dist[i - 1], d1 = dist[i];
        if (d1 == d0) return elev[i - 1];
        final t = (d - d0) / (d1 - d0);
        return elev[i - 1] + t * (elev[i] - elev[i - 1]);
      }
    }
    return elev.last;
  }
}
