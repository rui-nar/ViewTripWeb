/// Job notifier for async server-side A0 poster generation (issue #14, unit F).
///
/// Talks to the frozen contract in `api/poster.py`:
///   POST /api/projects/{name}/poster                  -> {job_id}
///   GET  /api/projects/{name}/poster/{job_id}          -> {status, stage, error_message}
///   GET  /api/projects/{name}/poster/{job_id}/download  -> file bytes
///   POST /api/projects/{name}/poster/preview           -> PNG bytes (fast, no job)
library;

import 'package:flutter/foundation.dart';

import '../api/client.dart';

/// Converts a memory item (as found in `ProjectNotifier.items`) to the
/// `PosterMemoryIn` shape the poster API expects.
Map<String, dynamic> posterMemoryJson(Map<String, dynamic> memory) => {
      'id': memory['id'],
      'lat': memory['lat'],
      'lon': memory['lon'],
      'date': memory['date'],
      'name': memory['name'],
      'description': memory['description'],
      'photo_uuids': (memory['photos'] as List?)?.cast<String>() ?? const [],
    };

/// Fetches a fast, low-resolution layout preview PNG for the given poster
/// request — same request shape as [PosterJobNotifier.start], but synchronous
/// (no job created, no polling): the server skips the Mapbox basemap fetch
/// entirely for this endpoint, so it returns in well under a second.
Future<Uint8List> fetchPosterPreview({
  required String projectName,
  required Map<String, double> bounds,
  required String orientation,
  required Map<String, bool> config,
  required List<Map<String, dynamic>> memories,
  ApiClient? client,
}) async {
  final res = await (client ?? api).postRaw(
    '/api/projects/${Uri.encodeComponent(projectName)}/poster/preview',
    {'bounds': bounds, 'orientation': orientation, 'config': config, 'memories': memories},
  );
  return res.bodyBytes;
}

/// Creates a poster job, then polls its status on a bounded interval until it
/// reaches a terminal state ('done'/'failed') or [maxPollAttempts] is
/// exhausted (treated as a failure). Consumers (a `Consumer`/
/// `ChangeNotifierProvider` widget) read [status]/[stage]/[error] and call
/// [downloadPath] once [status] is 'done'.
class PosterJobNotifier extends ChangeNotifier {
  final ApiClient _api;
  final String projectName;
  final Duration pollInterval;
  final int maxPollAttempts;

  PosterJobNotifier({
    required this.projectName,
    ApiClient? client,
    this.pollInterval = const Duration(seconds: 2),
    this.maxPollAttempts = 60,
  }) : _api = client ?? api;

  int? jobId;

  /// 'idle' | 'pending' | 'running' | 'done' | 'failed'
  String status = 'idle';
  String? stage;
  String? error;

  bool get isBusy => status == 'pending' || status == 'running';
  bool get isDone => status == 'done';
  bool get isFailed => status == 'failed';

  String get _encName => Uri.encodeComponent(projectName);

  /// Starts a poster job for the given request body and polls it to
  /// completion. [bounds] is `{north, south, east, west}`; [config] matches
  /// `PosterConfigIn`'s field names (see [PosterConfigOptions.toJson]).
  Future<void> start({
    required Map<String, double> bounds,
    required String orientation,
    required Map<String, bool> config,
    required List<Map<String, dynamic>> memories,
  }) async {
    status = 'pending';
    error = null;
    notifyListeners();
    try {
      final result = await _api.post('/api/projects/$_encName/poster', {
        'bounds': bounds,
        'orientation': orientation,
        'config': config,
        'memories': memories,
      }) as Map<String, dynamic>;
      jobId = result['job_id'] as int?;
    } on ApiException catch (e) {
      status = 'failed';
      error = e.body;
      notifyListeners();
      return;
    } catch (e) {
      status = 'failed';
      error = e.toString();
      notifyListeners();
      return;
    }
    await _poll();
  }

  Future<void> _poll() async {
    final id = jobId;
    if (id == null) return;
    for (var i = 0; i < maxPollAttempts; i++) {
      try {
        final result = await _api.get('/api/projects/$_encName/poster/$id')
            as Map<String, dynamic>;
        status = result['status'] as String? ?? status;
        stage = result['stage'] as String?;
        if (status == 'done') {
          notifyListeners();
          return;
        }
        if (status == 'failed') {
          error = result['error_message'] as String?;
          notifyListeners();
          return;
        }
        notifyListeners();
      } on ApiException catch (e) {
        status = 'failed';
        error = e.body;
        notifyListeners();
        return;
      } catch (e) {
        status = 'failed';
        error = e.toString();
        notifyListeners();
        return;
      }
      await Future.delayed(pollInterval);
    }
    status = 'failed';
    error = 'Poster generation timed out.';
    notifyListeners();
  }

  /// API path for downloading the rendered poster once [status] is 'done'.
  String downloadPath(String format) =>
      '/api/projects/$_encName/poster/$jobId/download?format=$format';
}
