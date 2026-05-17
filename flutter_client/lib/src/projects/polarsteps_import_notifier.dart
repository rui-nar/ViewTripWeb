import 'package:flutter/foundation.dart';

import '../api/client.dart';

class PolarstepsImportNotifier extends ChangeNotifier {
  // ── Trips ──────────────────────────────────────────────────────────────────
  List<Map<String, dynamic>> trips = [];
  Map<String, dynamic>? selectedTrip;
  bool isLoadingTrips = false;

  // ── Steps ──────────────────────────────────────────────────────────────────
  List<Map<String, dynamic>> steps = [];
  final Set<int> selectedStepIds = {};
  bool isLoadingSteps = false;

  // ── Import ─────────────────────────────────────────────────────────────────
  bool isImporting = false;
  int importedCount = 0;
  int importTotal = 0;

  String? error;
  bool polarstepsNotConnected = false;

  // ── Load trips ─────────────────────────────────────────────────────────────

  Future<void> loadTrips() async {
    isLoadingTrips = true;
    error = null;
    polarstepsNotConnected = false;
    notifyListeners();
    try {
      final raw =
          await api.get('/api/polarsteps/trips') as List<dynamic>;
      trips = raw.cast<Map<String, dynamic>>();
    } on ApiException catch (e) {
      if (e.statusCode == 400 &&
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
    isLoadingSteps = true;
    error = null;
    notifyListeners();
    try {
      final tripId = trip['id'] as int;
      final raw =
          await api.get('/api/polarsteps/trips/$tripId/steps') as List<dynamic>;
      steps = raw.cast<Map<String, dynamic>>();
      // Pre-select all steps
      for (final s in steps) {
        final id = s['id'];
        if (id is int) selectedStepIds.add(id);
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
    notifyListeners();
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
      if (id is int) selectedStepIds.add(id);
    }
    notifyListeners();
  }

  void clearSelection() {
    selectedStepIds.clear();
    notifyListeners();
  }

  // ── Import ─────────────────────────────────────────────────────────────────

  /// Import selected steps as memories into [projectName].
  ///
  /// For each step: POST /api/memories/ then upload each photo.
  /// Returns the count of successfully created memories.
  Future<int> importSelected(String projectName) async {
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
    try {
      for (final step in toImport) {
        final date = step['date'] as String?;
        if (date == null) {
          importedCount++;
          notifyListeners();
          continue;
        }

        final name = (step['name'] as String?)?.isNotEmpty == true
            ? step['name'] as String
            : null;
        final description = step['description'] as String?;
        final lat = (step['lat'] as num?)?.toDouble();
        final lon = (step['lon'] as num?)?.toDouble();

        final body = <String, dynamic>{
          'project_name': projectName,
          'date': date,
          'geo_mode': (lat != null && lon != null) ? 'custom' : 'start_of_day',
          if (name != null) 'name': name,
          if (description != null) 'description': description,
          if (lat != null) 'lat': lat,
          if (lon != null) 'lon': lon,
        };

        try {
          final result = await api.post('/api/memories/', body)
              as Map<String, dynamic>;
          final memId = result['id']?.toString();

          // Upload photos for this step
          if (memId != null) {
            final photos = (step['photos'] as List?)
                    ?.cast<Map<String, dynamic>>() ??
                [];
            for (final photo in photos) {
              final url = photo['url'] as String?;
              if (url == null || url.isEmpty) continue;
              try {
                await _uploadPhotoFromUrl(memId, url);
              } catch (_) {
                // Non-fatal — skip individual photo failures
              }
            }
          }
          created++;
        } on Exception catch (e) {
          error = e.toString().replaceFirst('Exception: ', '');
        }

        importedCount++;
        notifyListeners();
      }
    } finally {
      isImporting = false;
      notifyListeners();
    }
    return created;
  }

  Future<void> _uploadPhotoFromUrl(String memId, String photoUrl) async {
    await api.post('/api/memories/$memId/photos/from-url', {'url': photoUrl});
  }
}
