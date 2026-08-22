/// Job creation for async server-side A0 poster generation (issue #14, unit F).
///
/// Talks to the frozen contract in `api/poster.py`:
///   POST /api/projects/{name}/poster           -> {job_id}
///   POST /api/projects/{name}/poster/preview   -> PNG bytes (fast, no job)
///
/// The render itself runs in a queued background worker and the user is
/// emailed a download link once it finishes (a parallel workstream), so the
/// client's job is only to kick the job off — it no longer polls
/// `GET .../poster/{job_id}` for status, and there is no client-side notion
/// of a job being "busy"/"done"/"failed" to track.
library;

import 'package:flutter/foundation.dart';

import '../api/client.dart';
import '../core/project_ref.dart';

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

/// A poster preview: the rendered PNG, plus a [warning] when the server could
/// render everything *except* the map imagery.
///
/// The distinction matters: a grey preview used to be indistinguishable from a
/// working one, so a broken `MAPBOX_TOKEN` looked like a design choice rather
/// than a fault the user could act on.
class PosterPreview {
  final Uint8List bytes;
  final String? warning;

  const PosterPreview({required this.bytes, this.warning});

  bool get hasWarning => warning != null && warning!.isNotEmpty;
}

/// Header the server uses to report a degraded (map-less) preview.
const kPosterWarningHeader = 'x-poster-warning';

/// Fetches a fast, low-resolution preview of the real poster — same request
/// shape as [createPosterJob], but synchronous (no job created). The preview
/// renders the same basemap, cards and placement as the full job, just
/// small, so what it shows is what the poster will look like.
Future<PosterPreview> fetchPosterPreview({
  required ProjectRef ref,
  required Map<String, double> bounds,
  required String orientation,
  required Map<String, bool> config,
  required List<Map<String, dynamic>> memories,
  ApiClient? client,
  // The server caps its own basemap fetch at an 8s wall-clock budget
  // (poster_renderer._PREVIEW_BASEMAP_BUDGET_S) and degrades to a warning
  // past that, but card layout/measurement on top of it still needs more
  // headroom than the API client's 30s default gives it in practice.
  Duration timeout = const Duration(seconds: 20),
}) async {
  final res = await (client ?? api).postRaw(
    ref.path('/poster/preview'),
    {'bounds': bounds, 'orientation': orientation, 'config': config, 'memories': memories},
    timeout: timeout,
  );
  // Dart's http package lower-cases response header names.
  return PosterPreview(
    bytes: res.bodyBytes,
    warning: res.headers[kPosterWarningHeader],
  );
}

/// Kicks off a poster job and returns its id. [bounds] is
/// `{north, south, east, west}`; [config] matches `PosterConfigIn`'s field
/// names (see `PosterConfigOptions.toJson`).
///
/// Returns as soon as the server has queued the job — it does not wait for
/// (or poll for) the render to finish. A blocking, undismissable "wait up to
/// 120s" dialog built on top of this used to time out on real A0 renders that
/// legitimately take longer, reporting a false failure while the server kept
/// working (issue #14 feedback). The user is emailed a download link when
/// the render actually completes, so there is nothing left to wait for here;
/// callers should treat a thrown [ApiException] (or any other error) as a
/// failure to *create* the job, not a failure of the render itself.
Future<int> createPosterJob({
  required ProjectRef ref,
  required Map<String, double> bounds,
  required String orientation,
  required Map<String, bool> config,
  required List<Map<String, dynamic>> memories,
  ApiClient? client,
}) async {
  final result = await (client ?? api).post(ref.path('/poster'), {
    'bounds': bounds,
    'orientation': orientation,
    'config': config,
    'memories': memories,
  }) as Map<String, dynamic>;
  return result['job_id'] as int;
}
