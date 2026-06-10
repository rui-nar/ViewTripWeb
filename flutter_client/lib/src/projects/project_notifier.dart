/// Notifier for a single open project — loads details + GeoJSON in parallel.
library;

import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart' show Color;
import 'package:http/http.dart' as http;
import '../api/client.dart';
import '../map/geo_point.dart';
import '../map/polyline_decoder.dart';
import 'project_filter_mixin.dart';
import 'project_journal_crud_mixin.dart';
import 'project_memory_crud_mixin.dart';
import 'project_segment_crud_mixin.dart';
import 'project_service.dart';

class ProjectNotifier extends ChangeNotifier
    with ProjectFilterMixin, ProjectJournalCrudMixin, ProjectMemoryCrudMixin, ProjectSegmentCrudMixin {
  final ProjectService _service;

  ProjectNotifier(this._service);

  @override String? projectName;
  @override List<Map<String, dynamic>> activities = [];
  @override List<Map<String, dynamic>> items = [];   // ordered project items (activities + segments + memories)
  @override Map<String, dynamic>? geo;
  bool isLoading = false;
  @override String? error;

  /// Progressive-loading flags — default true so manage-mode screens that use
  /// the base load() see no behaviour change.  Set to false at the start of
  /// loadShared() / loadView() and flipped to true as each phase completes.
  bool isMetaLoaded = true;
  bool isElevationLoaded = true;
  bool isGeoLoaded = true;

  /// The activity currently highlighted on the map. Null = no selection.
  @override dynamic selectedActivityId;

  /// The connecting segment currently highlighted on the map. Null = no selection.
  @override dynamic selectedSegmentId;

  /// The memory currently highlighted on the map/panel. Null = no selection.
  @override dynamic selectedMemoryId;

  /// The journal entry currently highlighted on the map/panel. Null = no selection.
  dynamic selectedJournalId;

  /// Whether journal markers and list items are visible.
  bool showJournals = true;

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

  // ── Share tokens ─────────────────────────────────────────────────────────
  String? shareToken;
  String? shareTokenNoMemories;

  // ── Auto-sync state ──────────────────────────────────────────────────────
  bool autoSyncEnabled = true;
  int? linkedPsTripId;
  double? lastStravaSyncAt;
  double? lastPsSyncAt;

  /// Non-null when background check found new items; cleared by markSynced().
  ({List<Map<String, dynamic>> strava, List<Map<String, dynamic>> polarsteps})? pendingSync;

  // ── Track style ───────────────────────────────────────────────────────────
  Color trackColor = const Color(0xFF6B7280); // gray-500 — shown while project loads
  Color? trackSecondaryColor; // null = auto-derive from primary
  double trackWidth = 2.5;
  bool alternatingTrackColors = false;
  Color? elevationChartColor; // null = use black
  bool elevationChartShowLine = true;

  // ── Translation languages ─────────────────────────────────────────────────
  List<String> languages = [];

  Future<void> setTrackStyle({
    Color? color,
    Object? secondaryColor = _kUnset, // pass null explicitly to clear
    double? width,
    bool? alternating,
    Object? elevationColor = _kUnset, // pass null explicitly to clear
    bool? elevationShowLine,
  }) async {
    if (color != null) trackColor = color;
    if (secondaryColor != _kUnset) trackSecondaryColor = secondaryColor as Color?;
    if (width != null) trackWidth = width;
    if (alternating != null) alternatingTrackColors = alternating;
    if (elevationColor != _kUnset) elevationChartColor = elevationColor as Color?;
    if (elevationShowLine != null) elevationChartShowLine = elevationShowLine;
    notifyListeners();
    final name = projectName;
    if (name == null) return;
    try {
      await _service.saveTrackStyle(
        name,
        trackColor: color != null ? _colorToHex(color) : null,
        trackSecondaryColor: secondaryColor != _kUnset
            ? (secondaryColor != null ? _colorToHex(secondaryColor as Color) : null)
            : _kUnset,
        trackWidth: width,
        alternating: alternating,
        elevationChartColor: elevationColor != _kUnset
            ? (elevationColor != null ? _colorToHex(elevationColor as Color) : null)
            : _kUnset,
        elevationChartShowLine: elevationShowLine,
      );
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  static const Object _kUnset = Object();

  Future<void> saveLanguages(List<String> langs) async {
    languages = List<String>.from(langs);
    notifyListeners();
    final name = projectName;
    if (name == null) return;
    try {
      await _service.saveLanguages(name, langs);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  static String _colorToHex(Color c) =>
      '#${(c.toARGB32() & 0xFFFFFF).toRadixString(16).padLeft(6, '0').toUpperCase()}';

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
    selectedJournalId = null;
    selectedDay = null;
    selectedDays = {};
    notifyListeners();
  }

  void selectSegment(dynamic id) {
    selectedSegmentId =
        selectedSegmentId?.toString() == id?.toString() ? null : id;
    selectedActivityId = null;
    selectedMemoryId = null;
    selectedJournalId = null;
    selectedDay = null;
    selectedDays = {};
    notifyListeners();
  }

  void selectMemory(dynamic id) {
    selectedMemoryId =
        selectedMemoryId?.toString() == id?.toString() ? null : id;
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedJournalId = null;
    selectedDay = null;
    selectedDays = {};
    notifyListeners();
  }

  void selectJournal(dynamic id) {
    selectedJournalId =
        selectedJournalId?.toString() == id?.toString() ? null : id;
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedMemoryId = null;
    selectedDay = null;
    selectedDays = {};
    notifyListeners();
  }

  void toggleJournals() {
    showJournals = !showJournals;
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
  /// Subclasses can return false to skip owner-only authenticated calls
  /// (sync-meta, share-info, background sync check).
  bool get loadOwnerExtras => true;

  // Tracks the name/token passed to the current load() call so Phase 2 can
  // detect navigation-away without comparing against the mutable projectName
  // field (which is overwritten with the real project name during Phase 1).
  String? _loadKey;

  Timer? _photoPollingTimer;

  Future<void> load(String name) async {
    if (name.isEmpty) return;
    _stopPhotoPolling();
    _loadKey = name;
    projectName = name;
    isLoading = true;
    error = null;
    activities = [];
    items = [];
    geo = null;
    clearSegmentOverlay();  // discard any prior project's pending segment patches
    selectedActivityId = null;
    selectedSegmentId = null;
    selectedMemoryId = null;
    selectedDay = null;
    selectedDays = {};
    pendingSync = null;
    notifyListeners();

    try {
      // Fire both simultaneously.  /meta omits elevation_profile (~12 MB) so
      // the panel becomes interactive in ~1-2 s instead of ~17 s.  Elevation
      // data is fetched separately in the background (see below).
      final detailsFuture = _service.getDetailsMeta(name);
      final lowResFuture = _service.getLowResGeo(name);

      geo = await lowResFuture;
      if (_loadKey == name) notifyListeners(); // map visible at ~2.2s

      final details = await detailsFuture;
      if (_loadKey != name) return;

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
      final rawColor = details['track_color'] as String?;
      if (rawColor != null && rawColor.length == 7 && rawColor.startsWith('#')) {
        trackColor = Color(int.parse(rawColor.substring(1), radix: 16) | 0xFF000000);
      }
      final rawSecColor = details['track_secondary_color'] as String?;
      trackSecondaryColor = (rawSecColor != null && rawSecColor.length == 7 && rawSecColor.startsWith('#'))
          ? Color(int.parse(rawSecColor.substring(1), radix: 16) | 0xFF000000)
          : null;
      final rawWidth = details['track_width'] as num?;
      if (rawWidth != null) trackWidth = rawWidth.toDouble();
      final rawAlt = details['alternating_track_colors'] as bool?;
      if (rawAlt != null) alternatingTrackColors = rawAlt;
      final rawElColor = details['elevation_chart_color'] as String?;
      elevationChartColor = (rawElColor != null && rawElColor.length == 7 && rawElColor.startsWith('#'))
          ? Color(int.parse(rawElColor.substring(1), radix: 16) | 0xFF000000)
          : null;
      final rawElLine = details['elevation_chart_show_line'] as bool?;
      if (rawElLine != null) elevationChartShowLine = rawElLine;
      final rawLangs = details['languages'];
      if (rawLangs is List) languages = rawLangs.cast<String>();
      _updateStats();
      _buildFullTrack();
      _autoFillDaysToToday();  // fill missing dates in-memory before first render
      if (loadOwnerExtras) {
        await Future.wait([_loadSyncMeta(name), _loadShareInfo(name)]);
      }
    } on Exception catch (e) {
      error = _msg(e);
    } finally {
      isLoading = false;
      notifyListeners();   // map appears here with low-res straight lines
    }

    // Phase 2: full-res GeoJSON + elevation data in background.
    _loadFullGeoProgressively(name);
    _loadElevationData(name);
    // Recover any segment left "pending" by a resolve job that never finished
    // (e.g. the server restarted mid-resolve). Owner-editable loads only.
    if (loadOwnerExtras) recoverStalePendingSegments(name);
    // Background sync check — fires only for active trips with auto-sync on.
    // Delayed 5s so it doesn't compete with the full-res geo fetch on load.
    if (loadOwnerExtras && _tripIsActive && autoSyncEnabled) {
      Future.delayed(const Duration(seconds: 5), () {
        if (_loadKey == name) _backgroundSyncCheck(name);
      });
    }
  }

  /// Fetches full-res GeoJSON and progressively replaces each activity's
  /// straight-line approximation with its real GPS trace (last activity first).
  Future<void> _loadFullGeoProgressively(String name) async {
    // Guard: abort if the user navigated away before we finish
    if (_loadKey != name) return;
    try {
      final fullGeo = await _service.getGeo(name);
      if (_loadKey != name) return;

      // Drop overlay entries the server geo already reflects, so the durable
      // overlay self-cleans once the backend has caught up.
      reconcileSegmentOverlay(fullGeo);

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

      // Read geo fresh on every iteration so concurrent CRUD patches (e.g. a
      // segment deletion mid-load) are never overwritten by the snapshot we
      // took at the start of this function.
      const batchSize = 3;
      int batchCount = 0;
      for (final actId in actIds) {
        if (_loadKey != name) return;
        final full = fullFeatures[actId];
        if (full == null) continue;
        final snapshot = geo;
        if (snapshot == null) continue;
        final features = List<dynamic>.from(snapshot['features'] as List? ?? []);
        final idx = features.indexWhere(
            (f) => (f as Map)['properties']?['activity_id']?.toString() == actId);
        if (idx >= 0) features[idx] = full;
        geo = {'type': 'FeatureCollection', 'features': features};
        batchCount++;
        if (batchCount % batchSize == 0) {
          notifyListeners();
          await Future.delayed(const Duration(milliseconds: 80));
        }
      }

      if (_loadKey != name) return;
      // Final pass: rebuild authoritatively from the server geo (activities at
      // full resolution + the server's segment features), then re-apply the
      // durable segment overlay so any local add/update/delete that happened
      // during this background load wins over the stale server snapshot. This
      // single deterministic merge replaces the old ad-hoc "safety net".
      final features = mergePendingSegmentPatches(
          List<dynamic>.from(fullGeo['features'] as List? ?? []));
      geo = {'type': 'FeatureCollection', 'features': features};
      _buildFullTrack();
      isGeoLoaded = true;
      notifyListeners();
    } on Exception catch (e) {
      // Non-fatal — low-res map is still shown
      error = _msg(e);
      notifyListeners();
    }
  }

  /// Fetches the full project details (including elevation_profile) in the
  /// background and merges them into the already-rendered activity list so the
  /// elevation chart and cursor-to-map sync become available without blocking
  /// the initial panel render.
  Future<void> _loadElevationData(String name) async {
    try {
      final details = await _service.getDetails(name);
      if (_loadKey != name) return;
      final rawActivities = details['activities'];
      if (rawActivities is List) {
        final byId = <String, Map<String, dynamic>>{};
        for (final a in rawActivities.cast<Map<String, dynamic>>()) {
          byId[a['id']?.toString() ?? ''] = a;
        }
        activities = [
          for (final a in activities) byId[a['id']?.toString()] ?? a,
        ];
        _buildFullTrack();
        notifyListeners();
      }
    } on Exception catch (_) {
      // Non-fatal — elevation chart simply stays empty.
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

  /// Merges full activity data (with elevation_profile) returned by the
  /// background full-details request into the already-rendered activity list,
  /// then rebuilds tracks and notifies listeners.
  /// Called by SharedProjectNotifier / ViewProjectNotifier after phase 2.
  @protected
  void applyFullActivities(List<Map<String, dynamic>> fullActivities) {
    final byId = {for (final a in fullActivities) a['id']?.toString(): a};
    activities = [
      for (final a in activities) byId[a['id']?.toString()] ?? a,
    ];
    _updateStats();
    _buildFullTrack();
    notifyListeners();
  }

  /// Guard used by staged-loading subclasses to detect navigation away.
  @protected
  String? get currentLoadKey => _loadKey;

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

  String photoThumbUrl(String memId, String uuid) =>
      '${api.baseUrl}/api/memories/$memId/photos/$uuid/thumb';

  String photoFullUrl(String memId, String uuid) =>
      '${api.baseUrl}/api/memories/$memId/photos/$uuid';

  Map<String, String> get photoAuthHeaders {
    final token = api.tokenForUpload;
    return token != null ? {'Authorization': 'Bearer $token'} : {};
  }

  // ── Auto-sync ─────────────────────────────────────────────────────────────

  Future<void> _loadSyncMeta(String name) async {
    try {
      final data = await api.get(
        '/api/projects/${Uri.encodeComponent(name)}/sync-meta',
      ) as Map<String, dynamic>;
      autoSyncEnabled = data['auto_sync_enabled'] as bool? ?? true;
      linkedPsTripId = data['linked_ps_trip_id'] as int?;
      lastStravaSyncAt = (data['last_strava_sync_at'] as num?)?.toDouble();
      lastPsSyncAt = (data['last_ps_sync_at'] as num?)?.toDouble();
    } catch (_) {
      // Non-fatal — use defaults
    }
  }

  Future<void> _loadShareInfo(String name) async {
    try {
      final data = await api.get(
        '/api/projects/${Uri.encodeComponent(name)}/share-info',
      ) as Map<String, dynamic>;
      shareToken = data['share_token'] as String?;
      shareTokenNoMemories = data['share_token_no_memories'] as String?;
    } catch (_) {
      // Non-fatal — use defaults
    }
  }

  Future<void> _backgroundSyncCheck(String name) async {
    try {
      final data = await api.get(
        '/api/projects/${Uri.encodeComponent(name)}/sync/check',
      ) as Map<String, dynamic>;
      final strava = (data['strava'] as List?)?.cast<Map<String, dynamic>>() ?? [];
      final ps = (data['polarsteps'] as List?)?.cast<Map<String, dynamic>>() ?? [];
      if ((strava.isNotEmpty || ps.isNotEmpty) && projectName == name) {
        pendingSync = (strava: strava, polarsteps: ps);
        notifyListeners();
      }
    } catch (_) {
      // Non-fatal — sync check failure is silent
    }
  }

  Future<void> saveSyncMeta({bool? autoSyncEnabled, int? linkedPsTripId, bool clearLinkedTrip = false}) async {
    final name = projectName;
    if (name == null) return;
    if (autoSyncEnabled != null) this.autoSyncEnabled = autoSyncEnabled;
    if (clearLinkedTrip) {
      this.linkedPsTripId = null;
    } else if (linkedPsTripId != null) {
      this.linkedPsTripId = linkedPsTripId;
    }
    notifyListeners();
    try {
      final body = <String, dynamic>{
        if (autoSyncEnabled != null) 'auto_sync_enabled': autoSyncEnabled,
      };
      if (clearLinkedTrip) {
        body['linked_ps_trip_id'] = null;
      } else if (linkedPsTripId != null) {
        body['linked_ps_trip_id'] = linkedPsTripId;
      }
      await api.put('/api/projects/${Uri.encodeComponent(name)}/sync-meta', body);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> markSynced() async {
    final name = projectName;
    if (name == null) return;
    final now = DateTime.now().millisecondsSinceEpoch / 1000.0;
    lastStravaSyncAt = now;
    lastPsSyncAt = now;
    pendingSync = null;
    notifyListeners();
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}/sync-meta',
        {'last_strava_sync_at': now, 'last_ps_sync_at': now},
      );
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  // ── Share ──────────────────────────────────────────────────────────────────

  Future<void> createShareToken() async {
    final name = projectName;
    if (name == null) throw Exception('No project open');
    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/share',
        {},
      ) as Map<String, dynamic>;
      shareToken = result['share_token'] as String?;
      notifyListeners();
    } on ApiException catch (e) {
      throw Exception(e.body);
    }
  }

  Future<void> revokeShareToken() async {
    final name = projectName;
    if (name == null) return;
    try {
      await api.delete('/api/projects/${Uri.encodeComponent(name)}/share');
      shareToken = null;
      notifyListeners();
    } on ApiException catch (e) {
      throw Exception(e.body);
    }
  }

  Future<void> createShareTokenNoMemories() async {
    final name = projectName;
    if (name == null) throw Exception('No project open');
    try {
      final result = await api.post(
        '/api/projects/${Uri.encodeComponent(name)}/share/no-memories',
        {},
      ) as Map<String, dynamic>;
      shareTokenNoMemories = result['share_token_no_memories'] as String?;
      notifyListeners();
    } on ApiException catch (e) {
      throw Exception(e.body);
    }
  }

  Future<void> revokeShareTokenNoMemories() async {
    final name = projectName;
    if (name == null) return;
    try {
      await api.delete(
          '/api/projects/${Uri.encodeComponent(name)}/share/no-memories');
      shareTokenNoMemories = null;
      notifyListeners();
    } on ApiException catch (e) {
      throw Exception(e.body);
    }
  }

  Future<Map<String, dynamic>> getShareVisitors() async {
    final name = projectName;
    if (name == null) return {};
    try {
      return await api.get(
        '/api/projects/${Uri.encodeComponent(name)}/share/visitors',
      ) as Map<String, dynamic>;
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

  /// Saves trip_start and trip_end in a single PUT. No-ops if neither changed.
  /// Optimistic update is applied immediately; no reload needed since the
  /// server only writes these two fields and returns them unchanged.
  Future<void> setTripDates(String? startStr, String? endStr) async {
    final name = projectName;
    if (name == null) return;
    if (tripStart == startStr && tripEnd == endStr) return;
    tripStart = startStr;
    tripEnd = endStr;
    notifyListeners();
    try {
      await api.put(
        '/api/projects/${Uri.encodeComponent(name)}',
        {'trip_start': startStr, 'trip_end': endStr},
      );
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  // ── Photo polling (post-import background download) ──────────────────────

  /// Polls memory photos every 3 s for up to 60 s after a Polarsteps import.
  /// Updates only the `photos` list inside each memory item so map markers
  /// refresh without a full reload.
  void startPhotoPolling(String projectName) {
    _stopPhotoPolling();
    var remainingTicks = 20; // 3 s × 20 = 60 s
    _photoPollingTimer = Timer.periodic(const Duration(seconds: 3), (_) async {
      if (remainingTicks <= 0 || this.projectName != projectName) {
        _stopPhotoPolling();
        return;
      }
      remainingTicks--;
      await _refreshMemoryPhotos(projectName);
    });
  }

  void _stopPhotoPolling() {
    _photoPollingTimer?.cancel();
    _photoPollingTimer = null;
  }

  Future<void> _refreshMemoryPhotos(String projectName) async {
    try {
      final details = await _service.getDetails(projectName);
      if (this.projectName != projectName) return;
      final rawItems = details['items'];
      if (rawItems is! List) return;
      final freshItems = rawItems.cast<Map<String, dynamic>>();
      final freshById = <String, Map<String, dynamic>>{};
      for (final item in freshItems) {
        if (item['item_type'] != 'memory') continue;
        final mem = item['memory'] as Map?;
        if (mem == null) continue;
        final id = mem['id']?.toString();
        if (id != null) freshById[id] = item;
      }
      var changed = false;
      for (int i = 0; i < items.length; i++) {
        if (items[i]['item_type'] != 'memory') continue;
        final mem = items[i]['memory'] as Map?;
        if (mem == null) continue;
        final id = mem['id']?.toString();
        if (id == null) continue;
        final fresh = freshById[id];
        if (fresh == null) continue;
        final oldCount = (mem['photos'] as List?)?.length ?? 0;
        final newCount = ((fresh['memory'] as Map?)?['photos'] as List?)?.length ?? 0;
        if (newCount != oldCount) {
          items[i] = fresh;
          changed = true;
        }
      }
      if (changed) notifyListeners();
    } catch (_) {}
  }

  bool _isDisposed = false;

  /// Whether this notifier is still mounted (not disposed). Background tasks
  /// (e.g. segment route polling) check this before touching captured UI such
  /// as a ScaffoldMessenger.
  bool get isAlive => !_isDisposed;

  @override
  void notifyListeners() {
    if (!_isDisposed) super.notifyListeners();
  }

  @override
  void dispose() {
    _isDisposed = true;
    _stopPhotoPolling();
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

  void removeItemLocally(int index) {
    if (index >= 0 && index < items.length) {
      final removed = items.removeAt(index);
      if (removed['item_type'] == 'activity') {
        final actId = removed['activity_id']?.toString();
        activities.removeWhere((a) => a['id']?.toString() == actId);
      }
    }
    notifyListeners();
  }

  Future<void> removeItem(int index) async {
    final name = projectName;
    if (name == null) return;
    removeItemLocally(index);
    try {
      await api.delete(
          '/api/projects/${Uri.encodeComponent(name)}/items/$index');
      await _silentReload(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  /// API-only delete used by the undo-aware dismiss flow: the local removal
  /// has already happened via [removeItemLocally].
  Future<void> confirmRemoveItem(int index) async {
    final name = projectName;
    if (name == null) return;
    try {
      await api.delete(
          '/api/projects/${Uri.encodeComponent(name)}/items/$index');
      await _silentReload(name);
    } on Exception catch (e) {
      error = _msg(e);
      notifyListeners();
    }
  }

  Future<void> sortItemsByDate() async {
    final name = projectName;
    if (name == null) return;
    try {
      await _service.sortItems(name);
      await _silentReloadDetailsOnly(name);
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


  /// Fills missing dayMeta entries from the earliest known date up to today,
  /// in memory only — does NOT write to the backend.  Real data is only
  /// persisted when the user edits a day or saves project settings.
  void _autoFillDaysToToday() {
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
      // Advance by date arithmetic, not by 24 h, so DST spring-forwards
      // don't leave cursor at 01:00 and cause today to be skipped.
      cursor = DateTime(cursor.year, cursor.month, cursor.day + 1);
    }
    if (!changed) return;
    dayMeta = updated;
  }

  /// Full reload: details + geo. Use when a mutation can change map geometry
  /// (remove item, add/update/delete segment, refresh activity).
  Future<void> _silentReload(String name) async {
    try {
      final results = await Future.wait([
        _service.getDetailsMeta(name),
        _service.getGeo(name),
      ]);
      final details = results[0];
      _applyDetails(details, name);
      _autoFillDaysToToday();
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
      final details = await _service.getDetailsMeta(name);
      _applyDetails(details, name);
      _autoFillDaysToToday();
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
    final rawColor = details['track_color'] as String?;
    if (rawColor != null && rawColor.length == 7 && rawColor.startsWith('#')) {
      trackColor = Color(int.parse(rawColor.substring(1), radix: 16) | 0xFF000000);
    }
    final rawWidth = details['track_width'] as num?;
    if (rawWidth != null) trackWidth = rawWidth.toDouble();
    final rawAlt = details['alternating_track_colors'] as bool?;
    if (rawAlt != null) alternatingTrackColors = rawAlt;
    final rawElColor = details['elevation_chart_color'] as String?;
    elevationChartColor = (rawElColor != null && rawElColor.length == 7 && rawElColor.startsWith('#'))
        ? Color(int.parse(rawElColor.substring(1), radix: 16) | 0xFF000000)
        : null;
    final rawElLine = details['elevation_chart_show_line'] as bool?;
    if (rawElLine != null) elevationChartShowLine = rawElLine;
    final rawLangs = details['languages'];
    if (rawLangs is List) languages = rawLangs.cast<String>();
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
