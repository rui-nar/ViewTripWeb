/// Mixin providing Segment CRUD operations to ProjectNotifier.
///
/// Also owns the geo-patch helpers (upsertSegmentInGeo, removeSegmentFromGeo)
/// and the great-circle / segment-feature geometry, which were only ever used
/// by segment operations.
library;

import 'dart:math' as math;

import 'package:flutter/foundation.dart';

import '../api/client.dart';
import 'project_service.dart';

mixin ProjectSegmentCrudMixin on ChangeNotifier {
  // ── Abstract: project state (satisfied by ProjectNotifier fields) ──────────
  String? get projectName;
  List<Map<String, dynamic>> get items;
  set items(List<Map<String, dynamic>> v);
  Map<String, dynamic>? get geo;
  set geo(Map<String, dynamic>? v);
  String? get error;
  set error(String? v);

  /// Access to the underlying ProjectService — satisfied by the notifier's
  /// `get service => _service` delegate.
  ProjectService get service;

  /// Details-only reload — thin delegate to _silentReloadDetailsOnly.
  Future<void> reloadDetailsOnly(String name);

  /// Format an Exception into a user-readable string — delegates to _msg.
  String errorMessage(Exception e);

  // ── Segment CRUD ───────────────────────────────────────────────────────────

  Future<String> addSegment({
    required String segmentType,
    required String label,
    required double startLat,
    required double startLon,
    required double endLat,
    required double endLon,
    int? insertAfterIndex,
    String? date,
    String? trainNumber,
    String? hafasProvider,
  }) async {
    final name = projectName;
    if (name == null) return '';
    final placeholder = {
      'item_type': 'segment',
      'segment': {
        'id': '__optimistic__',
        'segment_type': segmentType,
        'label': label,
        'date': date,
        'start': {'lat': startLat, 'lon': startLon},
        'end':   {'lat': endLat,   'lon': endLon},
      },
    };
    final insertAt = insertAfterIndex != null
        ? (insertAfterIndex + 1).clamp(0, items.length)
        : items.length;
    // Assign a new list so identical() in the panel detects the change.
    final newItems = List<Map<String, dynamic>>.from(items);
    newItems.insert(insertAt, placeholder);
    items = newItems;
    notifyListeners();
    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/segments',
        {
          'segment_type': segmentType,
          'label': label,
          'start_lat': startLat,
          'start_lon': startLon,
          'end_lat': endLat,
          'end_lon': endLon,
          if (insertAfterIndex != null) 'insert_after_index': insertAfterIndex,
          if (date != null) 'date': date,
          if (trainNumber != null) 'train_number': trainNumber,
          if (hafasProvider != null) 'hafas_provider': hafasProvider,
        },
      ) as Map<String, dynamic>;
      final newId = result['id'] as String;
      // Replace the optimistic placeholder with the confirmed segment,
      // creating a new list so identical() in the panel triggers a rebuild.
      items = [
        for (final item in items)
          if (item['item_type'] == 'segment' &&
              item['segment']?['id'] == '__optimistic__')
            {
              'item_type': 'segment',
              'segment': {
                'id': newId,
                'segment_type': segmentType,
                'label': label,
                'date': date,
                'start': {'lat': startLat, 'lon': startLon},
                'end': {'lat': endLat, 'lon': endLon},
              },
            }
          else
            item,
      ];
      upsertSegmentInGeo(newId, _segmentFeature(
          newId, segmentType, label, startLat, startLon, endLat, endLon));
      notifyListeners();
      return newId;
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
      return '';
    }
  }

  Future<void> updateSegment(
    String segId, {
    required String segmentType,
    required String label,
    required double startLat,
    required double startLon,
    required double endLat,
    required double endLon,
    String? date,
    String? trainNumber,
    String? hafasProvider,
    String? routeMode,
  }) async {
    final name = projectName;
    if (name == null) return;
    String? prevRouteMode;
    double? prevStartLat, prevStartLon, prevEndLat, prevEndLon;
    // Build a new list (new reference) so identical() in the panel fires.
    items = [
      for (final item in items)
        if (item['item_type'] == 'segment' &&
            item['segment']?['id']?.toString() == segId)
          () {
            final old = item['segment'] as Map;
            prevRouteMode = old['route_mode'] as String?;
            prevStartLat  = (old['start']?['lat'] as num?)?.toDouble();
            prevStartLon  = (old['start']?['lon'] as num?)?.toDouble();
            prevEndLat    = (old['end']?['lat'] as num?)?.toDouble();
            prevEndLon    = (old['end']?['lon'] as num?)?.toDouble();
            return {
              'item_type': 'segment',
              'segment': {
                ...Map<String, dynamic>.from(old),
                'segment_type': segmentType,
                'label': label,
                'date': date,
                'start': {'lat': startLat, 'lon': startLon},
                'end': {'lat': endLat, 'lon': endLon},
                if (routeMode != null) 'route_mode': routeMode,
              },
            };
          }()
        else
          item,
    ];
    notifyListeners();
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}/segments/${Uri.encodeComponent(segId)}',
        {
          'segment_type': segmentType,
          'label': label,
          'start_lat': startLat,
          'start_lon': startLon,
          'end_lat': endLat,
          'end_lon': endLon,
          if (date != null) 'date': date,
          if (trainNumber != null) 'train_number': trainNumber,
          if (hafasProvider != null) 'hafas_provider': hafasProvider,
          if (routeMode != null) 'route_mode': routeMode,
        },
      );
      final coordsChanged = prevStartLat != startLat || prevStartLon != startLon ||
          prevEndLat != endLat || prevEndLon != endLon;
      final resetToGreatCircle = coordsChanged || routeMode == 'great_circle';
      if (resetToGreatCircle || (prevRouteMode != 'rail' &&
                                  prevRouteMode != 'ferry' &&
                                  prevRouteMode != 'bus')) {
        upsertSegmentInGeo(segId, _segmentFeature(
            segId, segmentType, label, startLat, startLon, endLat, endLon));
      }
      notifyListeners();
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  /// Resolve OSM route geometry for a train, boat, or bus segment.
  /// On success updates the segment's feature in [geo] and notifies listeners.
  /// Returns the result map or throws on error.
  Future<Map<String, dynamic>> resolveTrainRoute(
    String segId, {
    String routeMode = 'rail',
    String? hafasProvider,
    String? trainNumber,
    String? date,
  }) async {
    final name = projectName;
    if (name == null) throw Exception('No project open');
    final result = await service.resolveTrainRoute(
      name, segId,
      hafasProvider: hafasProvider,
      trainNumber: trainNumber,
      date: date,
    );
    final rawPolyline = result['polyline'];
    if (rawPolyline is List) {
      final coords = rawPolyline
          .map((pt) => (pt is List) ? [pt[0] as num, pt[1] as num] : null)
          .whereType<List<num>>()
          .map((pt) => [pt[0].toDouble(), pt[1].toDouble()])
          .toList();
      String? segmentType;
      for (final item in items) {
        if (item['item_type'] == 'segment' &&
            item['segment']?['id']?.toString() == segId) {
          segmentType = item['segment']?['segment_type'] as String?;
          final seg = Map<String, dynamic>.from(item['segment'] as Map);
          seg['route_mode'] = routeMode;
          if (trainNumber != null) seg['train_number'] = trainNumber;
          if (hafasProvider != null) seg['hafas_provider'] = hafasProvider;
          item['segment'] = seg;
          break;
        }
      }
      final feature = {
        'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': coords},
        'properties': {
          'type': 'segment',
          'segment_id': segId,
          'route_mode': routeMode,
          if (segmentType != null) 'segment_type': segmentType,
        },
      };
      upsertSegmentInGeo(segId, feature);
      notifyListeners();
    }
    return result;
  }

  /// Immediately remove a segment from the local list and map — no server call.
  /// Replaces `items` with a new list so the identity check in
  /// _rebuildDisplayList detects the change and removes the dismissed widget
  /// from the tree before the SnackBar fires.
  void removeSegmentLocally(String segId) {
    items = items
        .where((item) =>
            !(item['item_type'] == 'segment' &&
              item['segment']?['id']?.toString() == segId))
        .toList();
    removeSegmentFromGeo(segId);
    notifyListeners();
  }

  Future<void> deleteSegment(String segId) async {
    final name = projectName;
    if (name == null) return;
    // removeSegmentLocally already called via onOptimistic before the undo window.
    // No reload needed — reloading would bring back other pending-delete segments
    // (still in the DB) and cause ghost reappearances while their toasts are active.
    try {
      await api.delete(
          '/api/projects/${Uri.encodeComponent(name)}/segments/${Uri.encodeComponent(segId)}');
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  // ── Geo patch helpers ─────────────────────────────────────────────────────

  /// Upsert a segment feature into [geo] by segment_id (adds if absent).
  void upsertSegmentInGeo(String segId, Map<String, dynamic> feature) {
    final current = geo;
    if (current == null) return;
    final features = List<dynamic>.from(current['features'] as List? ?? []);
    final idx = features.indexWhere(
        (f) => (f as Map)['properties']?['segment_id']?.toString() == segId);
    if (idx >= 0) {
      features[idx] = feature;
    } else {
      features.add(feature);
    }
    geo = {'type': 'FeatureCollection', 'features': features};
  }

  /// Remove a segment feature from [geo] by segment_id.
  void removeSegmentFromGeo(String segId) {
    final current = geo;
    if (current == null) return;
    final features = List<dynamic>.from(current['features'] as List? ?? []);
    features.removeWhere(
        (f) => (f as Map)['properties']?['segment_id']?.toString() == segId);
    geo = {'type': 'FeatureCollection', 'features': features};
  }

  // ── Geometry (SLERP great-circle, mirrors src/models/great_circle.py) ─────

  static List<List<double>> _greatCircleCoords(
      double lat1, double lon1, double lat2, double lon2, {int n = 50}) {
    double r(double d) => d * math.pi / 180;
    double d(double r) => r * 180 / math.pi;

    final p1 = r(lat1), l1 = r(lon1), p2 = r(lat2), l2 = r(lon2);
    final x1 = math.cos(p1) * math.cos(l1);
    final y1 = math.cos(p1) * math.sin(l1);
    final z1 = math.sin(p1);
    final x2 = math.cos(p2) * math.cos(l2);
    final y2 = math.cos(p2) * math.sin(l2);
    final z2 = math.sin(p2);

    final dot = (x1 * x2 + y1 * y2 + z1 * z2).clamp(-1.0, 1.0);
    final omega = math.acos(dot);

    if (omega < 1e-10 || (omega - math.pi).abs() < 1e-10) {
      return [[lon1, lat1], [lon2, lat2]];
    }
    final sinOmega = math.sin(omega);
    return List.generate(n, (i) {
      final t = i / (n - 1);
      final k1 = math.sin((1 - t) * omega) / sinOmega;
      final k2 = math.sin(t * omega) / sinOmega;
      final lat = d(math.asin((k1 * z1 + k2 * z2).clamp(-1.0, 1.0)));
      final lon = d(math.atan2(k1 * y1 + k2 * y2, k1 * x1 + k2 * x2));
      return [lon, lat];
    });
  }

  static Map<String, dynamic> _segmentFeature(
      String id, String type, String label,
      double startLat, double startLon, double endLat, double endLon) {
    return {
      'type': 'Feature',
      'geometry': {
        'type': 'LineString',
        'coordinates': _greatCircleCoords(startLat, startLon, endLat, endLon),
      },
      'properties': {
        'type': 'segment',
        'segment_id': id,
        'segment_type': type,
        'label': label,
      },
    };
  }
}
