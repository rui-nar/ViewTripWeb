/// Notifier for a single open project — loads details + GeoJSON in parallel.
library;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

import '../api/client.dart';
import '../map/polyline_decoder.dart';
import 'project_service.dart';

class ProjectNotifier extends ChangeNotifier {
  final ProjectService _service;

  ProjectNotifier(this._service);

  String? projectName;
  List<Map<String, dynamic>> activities = [];
  List<Map<String, dynamic>> items = [];   // ordered project items (activities + segments + memories)
  Map<String, dynamic>? geo;
  bool isLoading = false;
  String? error;

  /// The activity currently highlighted on the map. Null = no selection.
  dynamic selectedActivityId;

  /// The connecting segment currently highlighted on the map. Null = no selection.
  dynamic selectedSegmentId;

  /// The memory currently highlighted on the map/panel. Null = no selection.
  dynamic selectedMemoryId;

  /// The day currently selected in the activity panel ("YYYY-MM-DD" or null).
  String? selectedDay;

  /// Days selected in multi-select mode. Empty = no multi-day filter.
  Set<String> selectedDays = {};

  /// User-defined trip start date override ("YYYY-MM-DD"); null = infer from activities.
  String? tripStart;

  void selectActivity(dynamic id) {
    selectedActivityId =
        selectedActivityId?.toString() == id?.toString() ? null : id;
    selectedSegmentId = null;
    selectedMemoryId = null;
    selectedDay = null;
    selectedDays = {};
    notifyListeners();
  }

  void selectSegment(dynamic id) {
    selectedSegmentId =
        selectedSegmentId?.toString() == id?.toString() ? null : id;
    selectedActivityId = null;
    selectedMemoryId = null;
    selectedDay = null;
    selectedDays = {};
    notifyListeners();
  }

  void selectMemory(dynamic id) {
    selectedMemoryId =
        selectedMemoryId?.toString() == id?.toString() ? null : id;
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedDay = null;
    selectedDays = {};
    notifyListeners();
  }

  void selectDay(String? dateKey) {
    selectedDay = dateKey;
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedMemoryId = null;
    selectedDays = {};
    notifyListeners();
  }

  void selectDays(Set<String> days) {
    selectedDays = Set.from(days);
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedMemoryId = null;
    selectedDay = null;
    notifyListeners();
  }

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
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedMemoryId = null;
    selectedDay = null;
    selectedDays = {};
    notifyListeners();

    try {
      final results = await Future.wait([
        _service.getDetails(name),
        _service.getGeo(name),
      ]);

      final details = results[0];
      projectName = details['name'] as String? ?? name;
      tripStart = details['trip_start'] as String?;
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
      _buildFullTrack();
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

  /// Map cursor driven by the elevation chart touch position.
  /// Uses a ValueNotifier so only the marker layer rebuilds on cursor moves.
  final ValueNotifier<LatLng?> elevationCursorNotifier = ValueNotifier(null);

  /// Elevation chart cursor driven by a map tap.
  /// Holds the cumulative distance (km) of the nearest track point.
  final ValueNotifier<double?> mapCursorDistNotifier = ValueNotifier(null);

  /// Full distance-indexed track for all activities — used by the map panel
  /// to map a tapped LatLng back to a distance on the elevation chart.
  List<(double, LatLng)> _fullTrack = const [];
  List<(double, LatLng)> get fullTrack => _fullTrack;

  /// Per-activity distance-indexed tracks (0-based distances) — used by
  /// ElevationChart to map chart x-position to a map position.
  /// Keys are activity_id as String.
  Map<String, List<(double, LatLng)>> get perActivityTracks => _perActivityTracks;
  Map<String, List<(double, LatLng)>> _perActivityTracks = const {};

  void _buildFullTrack() {
    // Build a raw-coords map from GeoJSON without creating LatLng objects yet.
    // GeoJSON coordinates are [lon, lat] per spec.
    final geoCoords = <String, List>{};
    final features = geo?['features'];
    if (features is List) {
      for (final f in features) {
        if (f is! Map) continue;
        final props = f['properties'] as Map? ?? {};
        if (props['type'] == 'segment') continue;
        final actId = props['activity_id']?.toString();
        if (actId == null) continue;
        final coords = (f['geometry'] as Map? ?? {})['coordinates'];
        if (coords is List && coords.isNotEmpty) geoCoords[actId] = coords;
      }
    }

    final combined = <(double, LatLng)>[];
    final perAct = <String, List<(double, LatLng)>>{};
    double offsetKm = 0;
    for (final a in activities) {
      final profile = a['elevation_profile'];
      if (profile is! List || profile.isEmpty) continue;
      final actId = a['id']?.toString();
      final coords = actId != null ? geoCoords[actId] : null;
      final last = profile.last;
      final elevTotalKm = (last is List && last.isNotEmpty)
          ? (last[0] as num).toDouble()
          : 0.0;
      final actTrack = <(double, LatLng)>[];
      if (coords != null && coords.isNotEmpty) {
        if (coords.length >= profile.length) {
          // Fast path: create LatLng only for the points we actually use.
          for (int i = 0; i < profile.length; i++) {
            final pt = profile[i];
            final c = coords[i];
            if (pt is! List || pt.length < 2 || c is! List || c.length < 2) continue;
            actTrack.add((
              (pt[0] as num).toDouble(),
              LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()),
            ));
          }
        } else {
          // Haversine fallback: coords fewer than profile samples.
          final pts = <LatLng>[];
          for (final c in coords) {
            if (c is List && c.length >= 2) {
              pts.add(LatLng((c[1] as num).toDouble(), (c[0] as num).toDouble()));
            }
          }
          actTrack.addAll(buildTrackFromPolyline(pts, elevTotalKm: elevTotalKm));
        }
      }
      if (actId != null) perAct[actId] = actTrack;
      for (final pt in actTrack) {
        combined.add((pt.$1 + offsetKm, pt.$2));
      }
      if (elevTotalKm > 0) offsetKm += elevTotalKm;
    }
    _fullTrack = combined;
    _perActivityTracks = perAct;
  }

  void clear() {
    projectName = null;
    activities = [];
    items = [];
    geo = null;
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedMemoryId = null;
    selectedDay = null;
    selectedDays = {};
    tripStart = null;
    previewArcNotifier.value = null;
    elevationCursorNotifier.value = null;
    mapCursorDistNotifier.value = null;
    _fullTrack = const [];
    _perActivityTracks = const {};
    totalDistanceM = 0;
    totalMovingSeconds = 0;
    totalElevationGainM = 0;
    isLoading = false;
    error = null;
    notifyListeners();
  }

  Future<String?> renameProject(String newName) async {
    final name = projectName;
    if (name == null) return null;
    try {
      final result = await api.put(
        '/api/projects/${Uri.encodeComponent(name)}',
        {'new_name': newName},
      ) as Map<String, dynamic>;
      projectName = result['name'] as String;
      notifyListeners();
      return projectName;
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
      return null;
    }
  }

  Future<void> setTripStart(String? dateStr) async {
    final name = projectName;
    if (name == null) return;
    tripStart = dateStr;
    notifyListeners();
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}',
        {'trip_start': dateStr},
      );
      await _silentReload(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  @override
  void dispose() {
    previewArcNotifier.dispose();
    elevationCursorNotifier.dispose();
    mapCursorDistNotifier.dispose();
    super.dispose();
  }

  // ── Item management ────────────────────────────────────────────────────────

  Future<void> refreshActivity(int activityId) async {
    final name = projectName;
    if (name == null) return;
    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/activities/$activityId/refresh',
        {},
      ) as Map<String, dynamic>;
      final rawActivities = result['activities'];
      activities = rawActivities is List
          ? rawActivities.cast<Map<String, dynamic>>()
          : [];
      final rawItems = result['items'];
      items = rawItems is List ? rawItems.cast<Map<String, dynamic>>() : [];
      _updateStats();
      _buildFullTrack();
      // Refresh GeoJSON so the map polylines reflect the updated track.
      geo = await _service.getGeo(name);
      notifyListeners();
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> removeItem(int index) async {
    final name = projectName;
    if (name == null) return;
    // Immediate local update so the list responds without a blank flash.
    if (index >= 0 && index < items.length) {
      final removed = items.removeAt(index);
      if (removed['item_type'] == 'activity') {
        final actId = removed['activity_id']?.toString();
        activities.removeWhere((a) => a['id']?.toString() == actId);
      }
    }
    notifyListeners();
    try {
      await api.delete(
          '/api/projects/${Uri.encodeComponent(name)}/items/$index');
      await _silentReload(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> reorderItems(int fromIndex, int toIndex) async {
    final name = projectName;
    if (name == null) return;
    // Immediate local update so the list responds without a blank flash.
    final moved = items.removeAt(fromIndex);
    items.insert(toIndex, moved);
    notifyListeners();
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}/items/reorder',
        {'from_index': fromIndex, 'to_index': toIndex},
      );
      await _silentReload(name);
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
    String? date,
  }) async {
    final name = projectName;
    if (name == null) return;
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
    items.insert(insertAt, placeholder);
    notifyListeners();
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
          if (date != null) 'date': date,
        },
      );
      await _silentReload(name);
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
    String? date,
  }) async {
    final name = projectName;
    if (name == null) return;
    for (final item in items) {
      if (item['item_type'] == 'segment' &&
          item['segment']?['id']?.toString() == segId) {
        final seg = Map<String, dynamic>.from(item['segment'] as Map);
        seg['segment_type'] = segmentType;
        seg['label'] = label;
        seg['date'] = date;
        seg['start'] = {'lat': startLat, 'lon': startLon};
        seg['end']   = {'lat': endLat,   'lon': endLon};
        item['segment'] = seg;
        break;
      }
    }
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
        },
      );
      await _silentReload(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> deleteSegment(String segId) async {
    final name = projectName;
    if (name == null) return;
    items.removeWhere((item) =>
        item['item_type'] == 'segment' &&
        item['segment']?['id']?.toString() == segId);
    notifyListeners();
    try {
      await api.delete(
          '/api/projects/${Uri.encodeComponent(name)}/segments/${Uri.encodeComponent(segId)}');
      await _silentReload(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  // ── Memory CRUD ────────────────────────────────────────────────────────────

  Future<void> createMemory({
    required String date,
    required String geoMode,
    String? name,
    String? time,
    String? description,
    double? lat,
    double? lon,
    int? insertAfterIndex,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    // Optimistic placeholder
    final placeholder = {
      'item_type': 'memory',
      'memory': {
        'id': '__optimistic__',
        'name': name,
        'date': date,
        'time': time,
        'description': description,
        'photos': <String>[],
        'geo_mode': geoMode,
        'lat': lat,
        'lon': lon,
      },
    };
    final insertAt = insertAfterIndex != null
        ? (insertAfterIndex + 1).clamp(0, items.length)
        : items.length;
    items.insert(insertAt, placeholder);
    notifyListeners();
    try {
      await api.post('/api/memories/', {
        'project_name': projectName,
        'date': date,
        'geo_mode': geoMode,
        if (name != null) 'name': name,
        if (time != null) 'time': time,
        if (description != null) 'description': description,
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
        if (insertAfterIndex != null) 'insert_after_index': insertAfterIndex,
      });
      await _silentReload(projectName);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> updateMemory(
    String memoryId, {
    required String date,
    required String geoMode,
    String? name,
    String? time,
    String? description,
    double? lat,
    double? lon,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    // Optimistic update
    for (final item in items) {
      if (item['item_type'] == 'memory' &&
          item['memory']?['id']?.toString() == memoryId) {
        final mem = Map<String, dynamic>.from(item['memory'] as Map);
        mem['name'] = name;
        mem['date'] = date;
        mem['time'] = time;
        mem['description'] = description;
        mem['geo_mode'] = geoMode;
        mem['lat'] = lat;
        mem['lon'] = lon;
        item['memory'] = mem;
        break;
      }
    }
    notifyListeners();
    try {
      await api.put('/api/memories/$memoryId', {
        'date': date,
        'geo_mode': geoMode,
        if (name != null) 'name': name,
        if (time != null) 'time': time,
        if (description != null) 'description': description,
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
      });
      await _silentReload(projectName);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> deleteMemory(String memoryId) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    items.removeWhere((item) =>
        item['item_type'] == 'memory' &&
        item['memory']?['id']?.toString() == memoryId);
    notifyListeners();
    try {
      await api.delete('/api/memories/$memoryId');
      await _silentReload(projectName);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  /// Upload a photo for a memory. Returns the UUID string on success.
  Future<String?> uploadMemoryPhoto(
    String memoryId,
    Uint8List bytes,
    String filename,
  ) async {
    final token = api.tokenForUpload;
    if (token == null) return null;
    final baseUrl = api.baseUrl;
    final uri = Uri.parse('$baseUrl/api/memories/$memoryId/photos');
    final request = http.MultipartRequest('POST', uri)
      ..headers['Authorization'] = 'Bearer $token'
      ..files.add(http.MultipartFile.fromBytes(
        'file',
        bytes,
        filename: filename,
      ));
    try {
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      if (res.statusCode >= 200 && res.statusCode < 300) {
        // Parse uuid from response JSON
        final body = res.body;
        final match = RegExp(r'"uuid"\s*:\s*"([^"]+)"').firstMatch(body);
        return match?.group(1);
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  Future<void> deleteMemoryPhoto(String memoryId, String photoUuid) async {
    final projectName = this.projectName;
    try {
      await api.delete('/api/memories/$memoryId/photos/$photoUuid');
      if (projectName != null) await _silentReload(projectName);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  // ── Internal helpers ───────────────────────────────────────────────────────

  /// Reloads project data from the API without clearing existing state first.
  Future<void> _silentReload(String name) async {
    try {
      final results = await Future.wait([
        _service.getDetails(name),
        _service.getGeo(name),
      ]);
      final details = results[0];
      projectName = details['name'] as String? ?? name;
      tripStart = details['trip_start'] as String?;
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
      _buildFullTrack();
    } on Exception catch (e) {
      error = _msg(e);
    } finally {
      notifyListeners();
    }
  }

  String _msg(Exception e) {
    final s = e.toString();
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
    return m?.group(1) ?? s.replaceFirst('Exception: ', '');
  }
}
