/// Notifier for a single open project — loads details + GeoJSON in parallel.
library;

import 'package:flutter/foundation.dart';
import 'package:latlong2/latlong.dart';

import '../api/client.dart';
import 'project_service.dart';

class ProjectNotifier extends ChangeNotifier {
  final ProjectService _service;

  ProjectNotifier(this._service);

  String? projectName;
  List<Map<String, dynamic>> activities = [];
  List<Map<String, dynamic>> items = [];   // ordered project items (activities + segments)
  Map<String, dynamic>? geo;
  bool isLoading = false;
  String? error;

  // Cached aggregate stats — computed once in load(), not on every build.
  double totalDistanceM = 0;
  int totalMovingSeconds = 0;
  double totalElevationGainM = 0;

  /// Loads project details and GeoJSON concurrently.
  Future<void> load(String name) async {
    if (name.isEmpty) return;
    projectName = name;
    isLoading = true;
    error = null;
    activities = [];
    items = [];
    geo = null;
    notifyListeners();

    try {
      final results = await Future.wait([
        _service.getDetails(name),
        _service.getGeo(name),
      ]);

      final details = results[0];
      final rawActivities = details['activities'];
      activities = rawActivities is List
          ? rawActivities.cast<Map<String, dynamic>>()
          : [];
      final rawItems = details['items'];
      items = rawItems is List
          ? rawItems.cast<Map<String, dynamic>>()
          : [];
      geo = results[1];
      _updateStats();
    } on Exception catch (e) {
      error = _msg(e);
    } finally {
      isLoading = false;
      notifyListeners();
    }
  }

  void _updateStats() {
    double dist = 0;
    int moving = 0;
    double elev = 0;
    for (final a in activities) {
      dist   += (a['distance']              as num? ?? 0).toDouble();
      moving += (a['moving_time']           as num? ?? 0).toInt();
      elev   += (a['total_elevation_gain']  as num? ?? 0).toDouble();
    }
    totalDistanceM      = dist;
    totalMovingSeconds  = moving;
    totalElevationGainM = elev;
  }

  /// Live arc preview while a SegmentDialog is open.
  /// Uses a ValueNotifier so updates don't trigger a full notifyListeners().
  final ValueNotifier<List<LatLng>?> previewArcNotifier = ValueNotifier(null);

  List<LatLng>? get previewArc => previewArcNotifier.value;

  void setPreviewArc(List<LatLng>? arc) {
    previewArcNotifier.value = arc; // no notifyListeners() — only arc layer rebuilds
  }

  void clear() {
    projectName = null;
    activities = [];
    items = [];
    geo = null;
    previewArcNotifier.value = null;
    totalDistanceM = 0;
    totalMovingSeconds = 0;
    totalElevationGainM = 0;
    isLoading = false;
    error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    previewArcNotifier.dispose();
    super.dispose();
  }

  // ── Item management ────────────────────────────────────────────────────────

  Future<void> removeItem(int index) async {
    final name = projectName;
    if (name == null) return;
    try {
      await api.delete(
          '/api/projects/${Uri.encodeComponent(name)}/items/$index');
      await load(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> reorderItems(int fromIndex, int toIndex) async {
    final name = projectName;
    if (name == null) return;
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}/items/reorder',
        {'from_index': fromIndex, 'to_index': toIndex},
      );
      await load(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  // ── Segment CRUD ───────────────────────────────────────────────────────────

  Future<void> addSegment({
    required String segmentType,
    required String label,
    required double startLat,
    required double startLon,
    required double endLat,
    required double endLon,
    int? insertAfterIndex,
  }) async {
    final name = projectName;
    if (name == null) return;
    try {
      await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/segments',
        {
          'segment_type': segmentType,
          'label': label,
          'start_lat': startLat,
          'start_lon': startLon,
          'end_lat': endLat,
          'end_lon': endLon,
          if (insertAfterIndex != null) 'insert_after_index': insertAfterIndex,
        },
      );
      await load(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
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
  }) async {
    final name = projectName;
    if (name == null) return;
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
        },
      );
      await load(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> deleteSegment(String segId) async {
    final name = projectName;
    if (name == null) return;
    try {
      await api.delete(
          '/api/projects/${Uri.encodeComponent(name)}/segments/${Uri.encodeComponent(segId)}');
      await load(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  String _msg(Exception e) {
    final s = e.toString();
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
    return m?.group(1) ?? s.replaceFirst('Exception: ', '');
  }
}
