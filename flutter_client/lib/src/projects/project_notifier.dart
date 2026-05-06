/// Notifier for a single open project — loads details + GeoJSON in parallel.
library;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show Color;
import 'package:http/http.dart' as http;
import '../api/client.dart';
import '../map/geo_point.dart';
import '../map/polyline_decoder.dart';
import 'project_filter_mixin.dart';
import 'project_memory_crud_mixin.dart';
import 'project_segment_crud_mixin.dart';
import 'project_service.dart';

class ProjectNotifier extends ChangeNotifier
    with ProjectFilterMixin, ProjectMemoryCrudMixin, ProjectSegmentCrudMixin {
  final ProjectService _service;

  ProjectNotifier(this._service);

  @override String? projectName;
  @override List<Map<String, dynamic>> activities = [];
  @override List<Map<String, dynamic>> items = [];   // ordered project items (activities + segments + memories)
  @override Map<String, dynamic>? geo;
  bool isLoading = false;
  @override String? error;

  /// The activity currently highlighted on the map. Null = no selection.
  @override dynamic selectedActivityId;

  /// The connecting segment currently highlighted on the map. Null = no selection.
  @override dynamic selectedSegmentId;

  /// The memory currently highlighted on the map/panel. Null = no selection.
  @override dynamic selectedMemoryId;

  /// The day currently selected in the activity panel ("YYYY-MM-DD" or null).
  @override String? selectedDay;

  /// Days selected in multi-select mode. Empty = no multi-day filter.
  @override Set<String> selectedDays = {};

  /// User-defined trip start date override ("YYYY-MM-DD"); null = infer from activities.
  String? tripStart;

  /// User-defined trip end date ("YYYY-MM-DD"); null = trip still ongoing.
  String? tripEnd;

  /// True if the trip is still active (no tripEnd set, or tripEnd is today or later).
  bool get _tripIsActive {
    if (tripEnd == null) return true;
    final end = DateTime.tryParse(tripEnd!);
    if (end == null) return true;
    final now = DateTime.now();
    return !end.isBefore(DateTime(now.year, now.month, now.day));
  }

  /// Day metadata keyed by "YYYY-MM-DD".
  @override Map<String, Map<String, dynamic>> dayMeta = {};

  /// Project-specific list of sleeping type options.
  List<String> sleepingOptions = [];

  /// Group assignment for each sleeping option: name → "Outdoors"|"Indoors"|"Other".
  Map<String, String> sleepingOptionGroups = {};

  /// Project-defined counters: [{name: String, start: double}].
  List<Map<String, dynamic>> counters = [];

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

  static const _defaultSleepingGroups = {
    'Camping': 'Outdoors', 'Bivouac': 'Outdoors', 'Shelter': 'Outdoors',
    'Hotel': 'Indoors', 'Pension/Guesthouse': 'Indoors',
    'Apartment': 'Indoors', 'Warmshower': 'Indoors',
    'Friend': 'Other', 'Transportation': 'Other',
  };

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
      tripEnd = details['trip_end'] as String?;
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
      final rawGroups = details['sleeping_option_groups'];
      sleepingOptionGroups = rawGroups is Map
          ? Map<String, String>.from(rawGroups.cast<String, String>())
          : { for (final n in sleepingOptions) n: _defaultSleepingGroups[n] ?? 'Other' };
      final rawCounters = details['counters'];
      counters = rawCounters is List
          ? rawCounters.map((c) => Map<String, dynamic>.from(c as Map)).toList()
          : [];
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
    // Auto-fill empty day entries up to today while the trip is active
    _autoFillDaysToToday();
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
  final ValueNotifier<List<GeoPoint>?> previewArcNotifier = ValueNotifier(null);

  /// Map cursor driven by the elevation chart touch position.
  /// Uses a ValueNotifier so only the marker layer rebuilds on cursor moves.
  final ValueNotifier<GeoPoint?> elevationCursorNotifier = ValueNotifier(null);

  /// Elevation chart cursor driven by a map tap.
  /// Holds the cumulative distance (km) of the nearest track point.
  final ValueNotifier<double?> mapCursorDistNotifier = ValueNotifier(null);

  /// Full distance-indexed track for all activities — used by the map panel
  /// to map a tapped GeoPoint back to a distance on the elevation chart.
  List<(double, GeoPoint)> _fullTrack = const [];
  List<(double, GeoPoint)> get fullTrack => _fullTrack;

  /// Per-activity distance-indexed tracks (0-based distances) — used by
  /// ElevationChart to map chart x-position to a map position.
  /// Keys are activity_id as String.
  Map<String, List<(double, GeoPoint)>> get perActivityTracks => _perActivityTracks;
  Map<String, List<(double, GeoPoint)>> _perActivityTracks = const {};

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

    final combined = <(double, GeoPoint)>[];
    final perAct = <String, List<(double, GeoPoint)>>{};
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
      final actTrack = <(double, GeoPoint)>[];
      if (coords != null && coords.isNotEmpty) {
        if (coords.length >= profile.length) {
          // Fast path: build GeoPoint only for the points we actually use.
          for (int i = 0; i < profile.length; i++) {
            final pt = profile[i];
            final c = coords[i];
            if (pt is! List || pt.length < 2 || c is! List || c.length < 2) continue;
            actTrack.add((
              (pt[0] as num).toDouble(),
              (lat: (c[1] as num).toDouble(), lon: (c[0] as num).toDouble()),
            ));
          }
        } else {
          // Haversine fallback: coords fewer than profile samples.
          final pts = <GeoPoint>[];
          for (final c in coords) {
            if (c is List && c.length >= 2) {
              pts.add((lat: (c[1] as num).toDouble(), lon: (c[0] as num).toDouble()));
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
    resetFilters();
    tripStart = null;
    tripEnd = null;
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

  Future<void> setTripEnd(String? dateStr) async {
    final name = projectName;
    if (name == null) return;
    tripEnd = dateStr;
    notifyListeners();
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}',
        {'trip_end': dateStr},
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

  // ── Internal helpers ───────────────────────────────────────────────────────

  /// Reloads project data from the API without clearing existing state first.
  Future<void> saveDayMeta({
    required Map<String, Map<String, dynamic>> newDayMeta,
    List<String>? newSleepingOptions,
    Map<String, String>? newSleepingOptionGroups,
    List<Map<String, dynamic>>? newCounters,
  }) async {
    final name = projectName;
    if (name == null) return;
    dayMeta = newDayMeta;
    if (newSleepingOptions != null) sleepingOptions = newSleepingOptions;
    if (newSleepingOptionGroups != null) sleepingOptionGroups = newSleepingOptionGroups;
    if (newCounters != null) counters = newCounters;
    notifyListeners();
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}/day-meta',
        {
          'day_meta': newDayMeta,
          if (newSleepingOptions != null) 'sleeping_options': newSleepingOptions,
          if (newSleepingOptionGroups != null) 'sleeping_option_groups': newSleepingOptionGroups,
          if (newCounters != null) 'counters': newCounters,
        },
      );
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> updateSleepingOptions(
    List<String> opts, {
    Map<String, String>? groups,
  }) =>
      saveDayMeta(
        newDayMeta: dayMeta,
        newSleepingOptions: opts,
        newSleepingOptionGroups: groups,
      );

  Future<void> updateCounters(List<Map<String, dynamic>> newCounters) =>
      saveDayMeta(newDayMeta: dayMeta, newCounters: newCounters);

  /// Silently fills empty dayMeta entries from the earliest known date up to
  /// today, but only while the trip is active (no tripEnd or tripEnd >= today).
  Future<void> _autoFillDaysToToday() async {
    if (!_tripIsActive) return;

    final now = DateTime.now();
    final todayDate = DateTime(now.year, now.month, now.day);

    String? earliest = tripStart;
    if (dayMeta.isNotEmpty) {
      final minKey = (dayMeta.keys.toList()..sort()).first;
      if (earliest == null || minKey.compareTo(earliest) < 0) earliest = minKey;
    }
    for (final a in activities) {
      final d = a['start_date_local'] as String?;
      if (d != null && d.length >= 10) {
        final dk = d.substring(0, 10);
        if (earliest == null || dk.compareTo(earliest) < 0) earliest = dk;
      }
    }
    earliest ??= '${todayDate.year.toString().padLeft(4, '0')}-'
                 '${todayDate.month.toString().padLeft(2, '0')}-'
                 '${todayDate.day.toString().padLeft(2, '0')}';

    final startDate = DateTime.tryParse(earliest);
    if (startDate == null || startDate.isAfter(todayDate)) return;

    final updated = Map<String, Map<String, dynamic>>.from(dayMeta);
    bool changed = false;
    DateTime cursor = DateTime(startDate.year, startDate.month, startDate.day);
    while (!cursor.isAfter(todayDate)) {
      final key =
          '${cursor.year.toString().padLeft(4, '0')}-'
          '${cursor.month.toString().padLeft(2, '0')}-'
          '${cursor.day.toString().padLeft(2, '0')}';
      if (!updated.containsKey(key)) {
        updated[key] = {};
        changed = true;
      }
      cursor = cursor.add(const Duration(days: 1));
    }
    if (!changed) return;
    await saveDayMeta(newDayMeta: updated);
  }

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
    tripEnd     = details['trip_end']   as String?;
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

  // ── Mixin delegates (forward private helpers to ProjectMemoryCrudMixin) ────

  @override
  ProjectService get service => _service;

  @override
  Future<void> reloadDetailsOnly(String name) => _silentReloadDetailsOnly(name);

  @override
  String errorMessage(Exception e) => _msg(e);

  String _msg(Exception e) {
    final s = e.toString();
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
    return m?.group(1) ?? s.replaceFirst('Exception: ', '');
  }

}
