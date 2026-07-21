import 'package:flutter/foundation.dart';

import '../api/client.dart';
import '../core/project_ref.dart';

class PolarstepsImportNotifier extends ChangeNotifier {
  // Injectable so tests can supply an ApiClient backed by a MockClient.
  final ApiClient _api;

  PolarstepsImportNotifier({ApiClient? client}) : _api = client ?? api;

  // ── Project context ────────────────────────────────────────────────────────
  ProjectRef? _projectRef;
  set projectRef(ProjectRef value) => _projectRef = value;

  // ── Trips ──────────────────────────────────────────────────────────────────
  List<Map<String, dynamic>> trips = [];
  Map<String, dynamic>? selectedTrip;
  bool isLoadingTrips = false;

  // ── Steps ──────────────────────────────────────────────────────────────────
  List<Map<String, dynamic>> steps = [];
  final Set<int> selectedStepIds = {};
  final Set<int> alreadyImportedIds = {};
  bool isLoadingSteps = false;

  // ── Import ─────────────────────────────────────────────────────────────────
  bool isImporting = false;
  int importedCount = 0;
  int importTotal = 0;

  String? error;
  bool polarstepsNotConnected = false;

  // ── Token expiry / reconnect ─────────────────────────────────────────────────
  /// True when a Polarsteps call failed because the remember_token expired.
  /// The screen shows an inline reconnect panel instead of a raw error.
  bool tokenExpired = false;

  /// True while a reconnect (+ resume) is in flight.
  bool reconnecting = false;

  /// The operation to re-run after a successful reconnect (the call that hit
  /// the 401), so the user resumes exactly where they were.
  Future<void> Function()? _resumeAction;

  /// A 401 from a Polarsteps endpoint (detail contains "polarsteps"), as
  /// opposed to an app-JWT 401 (detail "Token expired"/"Invalid token") which
  /// must NOT be treated as a Polarsteps reconnect.
  bool _isPolarstepsAuth(ApiException e) =>
      e.statusCode == 401 && e.body.toLowerCase().contains('polarsteps');

  // ── Load trips ─────────────────────────────────────────────────────────────

  Future<void> loadTrips() async {
    isLoadingTrips = true;
    error = null;
    polarstepsNotConnected = false;
    notifyListeners();
    try {
      final raw =
          await _api.get('/api/polarsteps/trips') as List<dynamic>;
      trips = raw.cast<Map<String, dynamic>>();
    } on ApiException catch (e) {
      if (_isPolarstepsAuth(e)) {
        tokenExpired = true;
        _resumeAction = loadTrips;
      } else if (e.statusCode == 400 &&
          e.body.toLowerCase().contains('not connected')) {
        polarstepsNotConnected = true;
      } else {
        error = e.toString().replaceFirst('Exception: ', '');
      }
    } on Exception catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
    } finally {
      isLoadingTrips = false;
      notifyListeners();
    }
  }

  // ── Select trip → load steps ───────────────────────────────────────────────

  Future<void> selectTrip(Map<String, dynamic> trip) async {
    selectedTrip = trip;
    steps = [];
    selectedStepIds.clear();
    alreadyImportedIds.clear();
    isLoadingSteps = true;
    error = null;
    notifyListeners();
    try {
      final tripId = trip['id'] as int;
      final ref = _projectRef;
      final projectParam = ref != null
          ? ref.withOwner('?project_name=${Uri.encodeComponent(ref.name)}')
          : '';
      final raw = await _api.get(
              '/api/polarsteps/trips/$tripId/steps$projectParam')
          as List<dynamic>;
      steps = raw.cast<Map<String, dynamic>>();

      // Identify already-imported steps
      for (final s in steps) {
        if (s['already_imported'] == true) {
          final id = s['id'];
          if (id is int) alreadyImportedIds.add(id);
        }
      }

      // Pre-select only new (not yet imported) steps
      for (final s in steps) {
        final id = s['id'];
        if (id is int && !alreadyImportedIds.contains(id)) {
          selectedStepIds.add(id);
        }
      }
    } on ApiException catch (e) {
      if (_isPolarstepsAuth(e)) {
        // Keep selectedTrip so the reconnect resumes by reloading these steps.
        tokenExpired = true;
        _resumeAction = () => selectTrip(trip);
      } else {
        error = e.toString().replaceFirst('Exception: ', '');
      }
    } on Exception catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
    } finally {
      isLoadingSteps = false;
      notifyListeners();
    }
  }

  void clearTrip() {
    selectedTrip = null;
    steps = [];
    selectedStepIds.clear();
    alreadyImportedIds.clear();
    notifyListeners();
  }

  // ── Reconnect after token expiry ─────────────────────────────────────────────

  /// Re-validate a freshly pasted remember_token, then resume the call that
  /// hit the 401. Returns true on success. On failure (invalid token), keeps
  /// the reconnect panel up and surfaces [error].
  Future<bool> reconnect(String token) async {
    final trimmed = token.trim();
    if (trimmed.isEmpty) return false;
    reconnecting = true;
    error = null;
    notifyListeners();
    try {
      await _api.post('/api/polarsteps/connect', {'remember_token': trimmed});
    } on ApiException catch (e) {
      error = _detail(e.body);
      reconnecting = false;
      notifyListeners();
      return false;
    } on Exception catch (e) {
      error = e.toString().replaceFirst('Exception: ', '');
      reconnecting = false;
      notifyListeners();
      return false;
    }

    // Token accepted — drop the expired state and resume where we left off.
    tokenExpired = false;
    final resume = _resumeAction;
    _resumeAction = null;
    notifyListeners();
    if (resume != null) await resume();
    reconnecting = false;
    notifyListeners();
    return true;
  }

  static String _detail(String body) {
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(body);
    return m?.group(1) ?? body;
  }

  // ── Selection ──────────────────────────────────────────────────────────────

  void toggleStep(int id) {
    if (selectedStepIds.contains(id)) {
      selectedStepIds.remove(id);
    } else {
      selectedStepIds.add(id);
    }
    notifyListeners();
  }

  void selectAll() {
    for (final s in steps) {
      final id = s['id'];
      if (id is int && !alreadyImportedIds.contains(id)) selectedStepIds.add(id);
    }
    notifyListeners();
  }

  void clearSelection() {
    selectedStepIds.clear();
    notifyListeners();
  }

  // ── Import ─────────────────────────────────────────────────────────────────

  /// Import selected steps as memories into [ref]'s project.
  ///
  /// For each step: POST /api/memories/ then upload each photo.
  /// Returns the count of successfully created memories.
  Future<int> importSelected(ProjectRef ref) async {
    final toImport = steps
        .where((s) => selectedStepIds.contains(s['id'] as int?))
        .toList();
    if (toImport.isEmpty) return 0;

    isImporting = true;
    importedCount = 0;
    importTotal = toImport.length;
    error = null;
    notifyListeners();

    int created = 0;
    const batchSize = 8;

    try {
      for (int start = 0; start < toImport.length; start += batchSize) {
        final batch = toImport.sublist(
          start,
          (start + batchSize).clamp(0, toImport.length),
        );

        final results = await Future.wait(
          batch.map((step) => _importStep(step, ref)),
        );

        for (final ok in results) {
          if (ok) created++;
        }
        importedCount += batch.length;
        notifyListeners();
      }
    } finally {
      isImporting = false;
      notifyListeners();
    }
    return created;
  }

  Future<bool> _importStep(
    Map<String, dynamic> step,
    ProjectRef ref,
  ) async {
    final date = step['date'] as String?;
    if (date == null) return false;

    final name = (step['name'] as String?)?.isNotEmpty == true
        ? step['name'] as String
        : null;
    final description = step['description'] as String?;
    final lat = (step['lat'] as num?)?.toDouble();
    final lon = (step['lon'] as num?)?.toDouble();
    final stepId = step['id'] as int?;

    final body = <String, dynamic>{
      'project_name': ref.name,
      'date': date,
      'geo_mode': (lat != null && lon != null) ? 'custom' : 'start_of_day',
      if (name != null) 'name': name,
      if (description != null) 'description': description,
      if (lat != null) 'lat': lat,
      if (lon != null) 'lon': lon,
      if (stepId != null) 'polarsteps_step_id': stepId,
    };

    try {
      final result = await _postWithRetry(ref.withOwner('/api/memories/'), body);
      final memId = result['id']?.toString();
      if (memId != null) {
        // Photo uploads return 202 immediately (background download on server).
        // Fire all in parallel — no need to await sequentially.
        final photos =
            (step['photos'] as List?)?.cast<Map<String, dynamic>>() ?? [];
        await Future.wait([
          for (final photo in photos)
            if ((photo['url'] as String?)?.isNotEmpty == true)
              _uploadPhotoFromUrl(memId, photo['url'] as String)
                  .catchError((_) {}),
        ]);
      }
      return true;
    } on Exception catch (_) {
      return false; // silently skip — server retried already, count will reflect actual imported
    }
  }

  Future<void> _uploadPhotoFromUrl(String memId, String photoUrl) async {
    await _api.post('/api/memories/$memId/photos/from-url', {'url': photoUrl});
  }

  /// POST with automatic retry on 5xx — handles transient server errors
  /// (DB startup race, SQLite lock contention, temporary overload).
  Future<Map<String, dynamic>> _postWithRetry(
    String url,
    Map<String, dynamic> body, {
    int maxAttempts = 3,
  }) async {
    for (int attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        return await _api.post(url, body) as Map<String, dynamic>;
      } on ApiException catch (e) {
        if (e.statusCode >= 500 && attempt < maxAttempts - 1) {
          await Future.delayed(Duration(milliseconds: 600 * (attempt + 1)));
          continue;
        }
        rethrow;
      }
    }
    throw StateError('unreachable');
  }
}
