/// Notifier for a single open project — loads details + GeoJSON in parallel.
library;

import 'dart:math' as math;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show Color;
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

  /// Day metadata keyed by "YYYY-MM-DD".
  Map<String, Map<String, dynamic>> dayMeta = {};

  /// Project-specific list of sleeping type options.
  List<String> sleepingOptions = [];

  /// Active tag filter — days not matching any of these tags are hidden.
  /// Empty = show all days.
  Set<String> _tagFilter = {};
  Set<String> get tagFilter => Set.unmodifiable(_tagFilter);

  /// All tags currently assigned to any day in this project (sorted).
  List<String> get availableTags {
    final tags = <String>{};
    for (final meta in dayMeta.values) {
      final t = meta['tags'];
      if (t is List) tags.addAll(t.cast<String>());
    }
    return tags.toList()..sort();
  }

  /// Apply a tag filter: drives selectedDays to matching day keys.
  void setTagFilter(Set<String> tags) {
    _tagFilter = Set.of(tags);
    if (_tagFilter.isEmpty) {
      selectedDays = {};
    } else {
      final matching = <String>{};
      for (final entry in dayMeta.entries) {
        final t = entry.value['tags'];
        if (t is List && t.any((x) => _tagFilter.contains(x as String))) {
          matching.add(entry.key);
        }
      }
      selectedDays = matching;
    }
    selectedDay = null;
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedMemoryId = null;
    notifyListeners();
  }

  // ── Track style (UI-only, not persisted to server) ───────────────────────
  Color trackColor = const Color(0xFFF97316);
  double trackWidth = 2.5;
  bool alternatingTrackColors = false;

  void setTrackStyle({Color? color, double? width, bool? alternating}) {
    if (color != null) trackColor = color;
    if (width != null) trackWidth = width;
    if (alternating != null) alternatingTrackColors = alternating;
    notifyListeners();
  }

  static const _defaultSleepingOptions = [
    'Camping', 'Bivouac', 'Shelter', 'Pension/Guesthouse', 'Hotel', 'Apartment',
  ];

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

  /// Loads project details and GeoJSON in two phases.
  ///
  /// Phase 1 (fast): fetches details + low-res GeoJSON in parallel.
  /// The map renders immediately with straight-line approximations.
  ///
  /// Phase 2 (background): fetches full-res GeoJSON and progressively
  /// replaces each activity's straight line with its real GPS trace,
  /// starting from the last activity.
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
      // Phase 1: details + low-res geo (both fast — no polyline decoding)
      final results = await Future.wait([
        _service.getDetails(name),
        _service.getLowResGeo(name),
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
      final rawDm = details['day_meta'];
      dayMeta = rawDm is Map
          ? rawDm.map((k, v) => MapEntry(k as String, Map<String, dynamic>.from(v as Map)))
          : {};
      final rawOpts = details['sleeping_options'];
      final optList = rawOpts is List ? List<String>.from(rawOpts) : <String>[];
      sleepingOptions = optList.isNotEmpty ? optList : List<String>.from(_defaultSleepingOptions);
      geo = results[1];   // low-res — map renders immediately
      _updateStats();
      _buildFullTrack();
    } on Exception catch (e) {
      error = _msg(e);
    } finally {
      isLoading = false;
      notifyListeners();   // map appears here with low-res straight lines
    }

    // Phase 2: fetch full-res geo in background; replace features progressively
    _loadFullGeoProgressively(name);
  }

  /// Fetches full-res GeoJSON and progressively replaces each activity's
  /// straight-line approximation with its real GPS trace (last activity first).
  Future<void> _loadFullGeoProgressively(String name) async {
    // Guard: abort if the user navigated away before we finish
    if (projectName != name) return;
    try {
      final fullGeo = await _service.getGeo(name);
      if (projectName != name) return;

      // Index full-res features by activity_id
      final fullFeatures = <String, Map<String, dynamic>>{};
      for (final f in (fullGeo['features'] as List? ?? [])) {
        final actId = (f as Map)['properties']?['activity_id']?.toString();
        if (actId != null) fullFeatures[actId] = Map<String, dynamic>.from(f);
      }

      // Ordered activity IDs from items, reversed so last activity updates first
      final actIds = items
          .where((i) => i['item_type'] == 'activity')
          .map((i) => i['activity_id']?.toString())
          .whereType<String>()
          .toList()
          .reversed
          .toList();

      var currentFeatures = List<dynamic>.from(geo!['features'] as List? ?? []);

      const batchSize = 3;
      int batchCount = 0;
      for (final actId in actIds) {
        if (projectName != name) return;
        final full = fullFeatures[actId];
        if (full == null) continue;
        final idx = currentFeatures.indexWhere(
            (f) => (f as Map)['properties']?['activity_id']?.toString() == actId);
        if (idx >= 0) currentFeatures[idx] = full;
        geo = {'type': 'FeatureCollection', 'features': List.from(currentFeatures)};
        batchCount++;
        if (batchCount % batchSize == 0) {
          notifyListeners();
          await Future.delayed(const Duration(milliseconds: 80));
        }
      }

      if (projectName != name) return;
      // Final sync: replace full geo (picks up any segment differences too)
      geo = fullGeo;
      _buildFullTrack();
      notifyListeners();
    } on Exception catch (e) {
      // Non-fatal — low-res map is still shown
      error = _msg(e);
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

  /// Live arc preview while a SegmentDialog or LocationPickerDialog is open.
  /// Callers write directly to `.value` — updates don't trigger notifyListeners().
  final ValueNotifier<List<LatLng>?> previewArcNotifier = ValueNotifier(null);

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
    _tagFilter = {};
    tripStart = null;
    dayMeta = {};
    sleepingOptions = [];
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

  // ── API config pass-throughs ───────────────────────────────────────────────

  String get apiBaseUrl => api.baseUrl;
  String? get apiToken => api.tokenForUpload;

  // ── Share ──────────────────────────────────────────────────────────────────

  /// Creates (or retrieves) the public share token for this project.
  /// Throws [Exception] with a user-readable message on API error.
  Future<String> createShareToken() async {
    final name = projectName;
    if (name == null) throw Exception('No project open');
    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/share',
        {},
      ) as Map<String, dynamic>;
      return result['share_token'] as String? ?? '';
    } on ApiException catch (e) {
      throw Exception(e.body);
    }
  }

  /// Revokes the public share token for this project.
  /// Throws [Exception] with a user-readable message on API error.
  Future<void> revokeShareToken() async {
    final name = projectName;
    if (name == null) return;
    try {
      await api.delete('/api/projects/${Uri.encodeComponent(name)}/share');
    } on ApiException catch (e) {
      throw Exception(e.body);
    }
  }

  /// Fetches raw bytes for an export API path.
  /// Throws [Exception] with a user-readable message on API error.
  Future<http.Response> fetchExportBytes(String apiPath) async {
    try {
      return await api.getRaw(apiPath);
    } on ApiException catch (e) {
      throw Exception(e.body);
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
      await _silentReloadDetailsOnly(name);
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
      await _silentReloadDetailsOnly(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

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
    items.insert(insertAt, placeholder);
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
      _upsertSegmentInGeo(newId, _segmentFeature(
          newId, segmentType, label, startLat, startLon, endLat, endLon));
      await _silentReloadDetailsOnly(name);
      return newId;
    } on Exception catch (e) {
      error = _msg(e);
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
    for (final item in items) {
      if (item['item_type'] == 'segment' &&
          item['segment']?['id']?.toString() == segId) {
        final old = item['segment'] as Map;
        prevRouteMode = old['route_mode'] as String?;
        prevStartLat  = (old['start']?['lat'] as num?)?.toDouble();
        prevStartLon  = (old['start']?['lon'] as num?)?.toDouble();
        prevEndLat    = (old['end']?['lat'] as num?)?.toDouble();
        prevEndLon    = (old['end']?['lon'] as num?)?.toDouble();
        final seg = Map<String, dynamic>.from(old);
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
          if (trainNumber != null) 'train_number': trainNumber,
          if (hafasProvider != null) 'hafas_provider': hafasProvider,
          if (routeMode != null) 'route_mode': routeMode,
        },
      );
      final coordsChanged = prevStartLat != startLat || prevStartLon != startLon ||
          prevEndLat != endLat || prevEndLon != endLon;
      final resetToGreatCircle = coordsChanged || routeMode == 'great_circle';
      if (resetToGreatCircle || prevRouteMode != 'rail') {
        _upsertSegmentInGeo(segId, _segmentFeature(
            segId, segmentType, label, startLat, startLon, endLat, endLon));
      }
      await _silentReloadDetailsOnly(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  /// Resolve real railway geometry for a train segment via HAFAS + Overpass.
  /// On success updates the segment's feature in [geo] and notifies listeners.
  /// Returns the result map or throws on error.
  Future<Map<String, dynamic>> resolveTrainRoute(
    String segId, {
    String? hafasProvider,
    String? trainNumber,
    String? date,
  }) async {
    final name = projectName;
    if (name == null) throw Exception('No project open');
    final result = await _service.resolveTrainRoute(
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
      // Patch the segment's geo feature with the resolved rail polyline
      final feature = {
        'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': coords},
        'properties': {
          'type': 'segment',
          'segment_id': segId,
          'route_mode': 'rail',
        },
      };
      _upsertSegmentInGeo(segId, feature);
      // Update route_mode in local items list
      for (final item in items) {
        if (item['item_type'] == 'segment' &&
            item['segment']?['id']?.toString() == segId) {
          final seg = Map<String, dynamic>.from(item['segment'] as Map);
          seg['route_mode'] = 'rail';
          if (trainNumber != null) seg['train_number'] = trainNumber;
          if (hafasProvider != null) seg['hafas_provider'] = hafasProvider;
          item['segment'] = seg;
          break;
        }
      }
      notifyListeners();
    }
    return result;
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
      _removeSegmentFromGeo(segId);
      await _silentReloadDetailsOnly(name);
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
      await _silentReloadDetailsOnly(projectName);
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
      await _silentReloadDetailsOnly(projectName);
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
      await _silentReloadDetailsOnly(projectName);
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
      if (projectName != null) await _silentReloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  // ── Internal helpers ───────────────────────────────────────────────────────

  /// Reloads project data from the API without clearing existing state first.
  Future<void> saveDayMeta({
    required Map<String, Map<String, dynamic>> newDayMeta,
    List<String>? newSleepingOptions,
  }) async {
    final name = projectName;
    if (name == null) return;
    dayMeta = newDayMeta;
    if (newSleepingOptions != null) sleepingOptions = newSleepingOptions;
    notifyListeners();
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}/day-meta',
        {
          'day_meta': newDayMeta,
          if (newSleepingOptions != null) 'sleeping_options': newSleepingOptions,
        },
      );
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> updateSleepingOptions(List<String> opts) =>
      saveDayMeta(newDayMeta: dayMeta, newSleepingOptions: opts);

  /// Full reload: details + geo. Use when a mutation can change map geometry
  /// (remove item, add/update/delete segment, refresh activity).
  Future<void> _silentReload(String name) async {
    try {
      final results = await Future.wait([
        _service.getDetails(name),
        _service.getGeo(name),
      ]);
      final details = results[0];
      _applyDetails(details, name);
      geo = results[1];
      _updateStats();
      _buildFullTrack();
    } on Exception catch (e) {
      error = _msg(e);
    } finally {
      notifyListeners();
    }
  }

  /// Details-only reload: skips the heavy GeoJSON fetch. Use when a mutation
  /// cannot change map geometry (reorder, trip-start, memory CRUD).
  Future<void> _silentReloadDetailsOnly(String name) async {
    try {
      final details = await _service.getDetails(name);
      _applyDetails(details, name);
      _updateStats();
    } on Exception catch (e) {
      error = _msg(e);
    } finally {
      notifyListeners();
    }
  }

  void _applyDetails(dynamic details, String name) {
    projectName = details['name'] as String? ?? name;
    tripStart   = details['trip_start'] as String?;
    final rawActivities = details['activities'];
    activities = rawActivities is List
        ? rawActivities.cast<Map<String, dynamic>>()
        : [];
    final rawItems = details['items'];
    items = rawItems is List
        ? rawItems.cast<Map<String, dynamic>>()
        : [];
    final rawDm = details['day_meta'];
    dayMeta = rawDm is Map
        ? rawDm.map((k, v) => MapEntry(k as String, Map<String, dynamic>.from(v as Map)))
        : {};
    final rawOpts = details['sleeping_options'];
    sleepingOptions = rawOpts is List
        ? List<String>.from(rawOpts)
        : List<String>.from(_defaultSleepingOptions);
  }

  String _msg(Exception e) {
    final s = e.toString();
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
    return m?.group(1) ?? s.replaceFirst('Exception: ', '');
  }

  // ── Great-circle helpers (mirrors src/models/great_circle.py) ─────────────

  /// SLERP great-circle arc — returns GeoJSON [lon, lat] coordinate pairs.
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

    final dot = (x1*x2 + y1*y2 + z1*z2).clamp(-1.0, 1.0);
    final omega = math.acos(dot);

    if (omega < 1e-10 || (omega - math.pi).abs() < 1e-10) {
      return [[lon1, lat1], [lon2, lat2]];
    }
    final sinOmega = math.sin(omega);
    return List.generate(n, (i) {
      final t = i / (n - 1);
      final k1 = math.sin((1 - t) * omega) / sinOmega;
      final k2 = math.sin(t * omega) / sinOmega;
      final lat = d(math.asin((k1*z1 + k2*z2).clamp(-1.0, 1.0)));
      final lon = d(math.atan2(k1*y1 + k2*y2, k1*x1 + k2*x2));
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

  /// Upsert a segment feature into [geo] by segment_id (adds if absent).
  void _upsertSegmentInGeo(String segId, Map<String, dynamic> feature) {
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
  void _removeSegmentFromGeo(String segId) {
    final current = geo;
    if (current == null) return;
    final features = List<dynamic>.from(current['features'] as List? ?? []);
    features.removeWhere(
        (f) => (f as Map)['properties']?['segment_id']?.toString() == segId);
    geo = {'type': 'FeatureCollection', 'features': features};
  }
}
