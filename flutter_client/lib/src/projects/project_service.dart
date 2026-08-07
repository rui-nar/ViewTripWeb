/// Single-project service — wraps /api/projects/{name} and /api/geo/* endpoints.
library;

import 'package:flutter/foundation.dart' show visibleForTesting;

import '../api/client.dart';
import '../core/project_ref.dart';
import '../map/polyline_decoder.dart';

class ProjectService {
  /// Fetches the full project dict for [ref] including elevation_profile data.
  /// GET /api/projects/{name}
  ///
  /// The heaviest endpoint in the app (~12 MB on a large trip), so it gets the
  /// most generous budget rather than the 30 s default it used to inherit.
  Future<Map<String, dynamic>> getDetails(ProjectRef ref) async {
    final data = await api.get(ref.path(), timeout: const Duration(minutes: 2));
    return data as Map<String, dynamic>;
  }

  /// Lightweight project dict — no elevation_profile or summary_polyline.
  /// Typically 10-15× smaller than getDetails(); use for initial load and
  /// reloads that don't need the elevation chart to update.
  /// GET /api/projects/{name}/meta
  ///
  /// 60 s, not the 30 s default: a cold load of a large project measured 11-13 s
  /// server-side before a byte of the body moved, so the default left almost no
  /// headroom for the transfer — see issue #178.
  Future<Map<String, dynamic>> getDetailsMeta(ProjectRef ref) async {
    final data = await api.get(ref.path('/meta'), timeout: _kLoadTimeout);
    return data as Map<String, dynamic>;
  }

  /// Budget for the two requests the activity panel blocks on (see
  /// getDetailsMeta and getLowResGeo). ProjectNotifier.load() retries them, so
  /// this is the wait before a *retry*, not before a visible failure.
  static const _kLoadTimeout = Duration(seconds: 60);

  /// Fetches the GeoJSON FeatureCollection for [ref].
  /// GET /api/geo/project?name={name}
  ///
  /// The full-res endpoint sends activity tracks as Google-encoded polylines
  /// (in `properties.polyline`, with empty `coordinates`) to keep the payload
  /// small; [_expandEncodedActivities] decodes them back to `coordinates` so
  /// the rest of the app sees standard GeoJSON. The timeout is generous because
  /// a cold-cache build of a large trip can take a while on NAS storage.
  Future<Map<String, dynamic>> getGeo(ProjectRef ref) async {
    final encoded = Uri.encodeComponent(ref.name);
    // Compact payload: activity tracks as Google-encoded polylines, decoded by
    // expandEncodedActivities (~4.5× smaller than expanded coordinates). The
    // earlier web crash — decodePolyline yielding a ~42e6 latitude — was a
    // Dart-on-web bitwise/`~` semantics bug, now fixed in the decoder itself
    // (see polyline_decoder.dart). The generous timeout covers a cold-cache
    // build of a large trip.
    final data = await api.get(
        ref.withOwner('/api/geo/project?name=$encoded&encoded=1'),
        timeout: const Duration(seconds: 90));
    return expandEncodedActivities(data as Map<String, dynamic>);
  }

  /// Expand any activity feature carrying a Google-encoded `polyline` property
  /// into a standard GeoJSON `coordinates` array (`[[lon, lat], …]`). No-op for
  /// features that already have coordinates (segments, straight-line fallbacks,
  /// and the share endpoint's expanded responses).
  @visibleForTesting
  static Map<String, dynamic> expandEncodedActivities(Map<String, dynamic> geo) {
    final features = geo['features'];
    if (features is! List) return geo;
    for (final f in features) {
      if (f is! Map) continue;
      final props = f['properties'];
      if (props is! Map) continue;
      final enc = props['polyline'];
      if (enc is! String || enc.isEmpty) continue;
      final geom = f['geometry'];
      if (geom is! Map) continue;
      final existing = geom['coordinates'];
      if (existing is List && existing.isNotEmpty) continue; // already expanded
      // Validate every decoded point: on the web the polyline decode can yield
      // out-of-range values, and a single bad latitude crashes flutter_map's
      // bounds assertion. Drop non-finite / out-of-range points rather than
      // ever handing them to the map. (Client-side decode is disabled for web in
      // getGeo; this is a defensive backstop for any other caller/platform.)
      final coords = <List<double>>[];
      for (final p in decodePolyline(enc)) {
        if (p.lat.isFinite && p.lon.isFinite &&
            p.lat >= -90 && p.lat <= 90 && p.lon >= -180 && p.lon <= 180) {
          coords.add([p.lon, p.lat]);
        }
      }
      if (coords.length >= 2) geom['coordinates'] = coords;
    }
    return geo;
  }

  /// Fetches pre-computed low-res GeoJSON (straight lines per activity) for [ref].
  /// GET /api/geo/project/low-res?name={name}
  Future<Map<String, dynamic>> getLowResGeo(ProjectRef ref) async {
    final encoded = Uri.encodeComponent(ref.name);
    final data = await api.get(
        ref.withOwner('/api/geo/project/low-res?name=$encoded'),
        timeout: _kLoadTimeout);
    return data as Map<String, dynamic>;
  }

  /// Fetches pre-computed project statistics for [ref].
  /// Pass [tags] to filter stats to only days with matching tags.
  /// GET /api/projects/{name}/stats[?tags=x&tags=y]
  Future<Map<String, dynamic>> getStats(ProjectRef ref,
      {List<String> tags = const []}) async {
    final query = tags.isEmpty
        ? ''
        : '?${tags.map((t) => 'tags=${Uri.encodeComponent(t)}').join('&')}';
    final data = await api.get(ref.path('/stats$query'));
    return data as Map<String, dynamic>;
  }

  /// PUT /api/projects/{name}/track-style
  Future<void> saveTrackStyle(
    ProjectRef ref, {
    String? trackColor,
    Object? trackSecondaryColor = _kUnset, // null = clear, _kUnset = don't send
    double? trackWidth,
    bool? alternating,
    Object? elevationChartColor = _kUnset, // null = clear, _kUnset = don't send
    bool? elevationChartShowLine,
    bool? colorByType,
    Map<String, Map<String, dynamic>>? typeStyles,
  }) async {
    await api.put(ref.path('/track-style'), {
      if (trackColor != null) 'track_color': trackColor,
      if (trackSecondaryColor != _kUnset) 'track_secondary_color': trackSecondaryColor,
      if (trackWidth != null) 'track_width': trackWidth,
      if (alternating != null) 'alternating_track_colors': alternating,
      if (elevationChartColor != _kUnset) 'elevation_chart_color': elevationChartColor,
      if (elevationChartShowLine != null) 'elevation_chart_show_line': elevationChartShowLine,
      if (colorByType != null) 'color_by_type': colorByType,
      if (typeStyles != null) 'type_styles': typeStyles,
    });
  }

  static const Object _kUnset = Object();

  /// PUT /api/projects/{name}/items/sort
  Future<void> sortItems(ProjectRef ref) async {
    await api.put(ref.path('/items/sort'), {});
  }

  /// PUT /api/projects/{name}/languages
  Future<void> saveLanguages(ProjectRef ref, List<String> languages) async {
    await api.put(ref.path('/languages'), {'languages': languages});
  }

  /// Fetch a single activity's editable geometry (polyline + elevation pairs).
  /// GET /api/projects/{name}/activities/{id}/track
  /// Far smaller than getDetails() — used to open the track editor without
  /// downloading the whole project.
  Future<Map<String, dynamic>> getActivityTrack(
    ProjectRef ref,
    int activityId,
  ) async {
    final data = await api.get(ref.path('/activities/$activityId/track'));
    return data as Map<String, dynamic>;
  }

  /// Replace an activity's track geometry with an edited point list.
  /// PUT /api/projects/{name}/activities/{id}/track
  /// [payload] is [TrackEditModel.toSavePayload]. Returns the updated project.
  ///
  /// Generous timeout: see splitActivity below — the same recompute +
  /// reload can run well over the client's default 30s on a large trip, and
  /// this response is discarded by the caller anyway (ProjectNotifier just
  /// re-fetches via _silentReload).
  Future<Map<String, dynamic>> saveActivityTrack(
    ProjectRef ref,
    int activityId,
    Map<String, dynamic> payload,
  ) async {
    final data = await api.put(
      ref.path('/activities/$activityId/track'),
      payload,
      timeout: const Duration(minutes: 2),
    );
    return data as Map<String, dynamic>;
  }

  /// Reset an edited activity's track to the original Strava geometry.
  /// POST /api/projects/{name}/activities/{id}/reset
  ///
  /// Generous timeout: see saveActivityTrack above.
  Future<Map<String, dynamic>> resetActivityTrack(
    ProjectRef ref,
    int activityId,
  ) async {
    final data = await api.post(
      ref.path('/activities/$activityId/reset'),
      const {},
      timeout: const Duration(minutes: 2),
    );
    return data as Map<String, dynamic>;
  }

  /// Split an activity at [splitIndex]; the tail becomes a new local activity.
  /// When [dropBoundary] is true, the tail excludes the shared boundary point
  /// (#104 — used when a transportation segment will bridge the cut).
  /// POST /api/projects/{name}/activities/{id}/split
  ///
  /// [payload] is the editor's current TrackEditModel.toSavePayload — the point
  /// list [splitIndex] indexes into. Sending it lets the server cut the track
  /// the user is actually looking at, so unsaved trims/deletes compound with
  /// the split instead of being discarded (#127). Omit it to split the stored
  /// geometry.
  ///
  /// Generous timeout: on a large trip, committing the split + reloading and
  /// serialising the updated project can take well over the client's default
  /// 30s (this response is discarded by the caller anyway — see
  /// ProjectNotifier.splitActivity — but the request still has to finish).
  Future<Map<String, dynamic>> splitActivity(
    ProjectRef ref,
    int activityId,
    int splitIndex, {
    bool dropBoundary = false,
    Map<String, dynamic>? payload,
  }) async {
    final data = await api.post(
      ref.path('/activities/$activityId/split'),
      {
        'split_index': splitIndex,
        'drop_boundary': dropBoundary,
        if (payload != null) ...payload,
      },
      timeout: const Duration(minutes: 2),
    );
    return data as Map<String, dynamic>;
  }

  /// Delete a local (split-tail, negative-id) activity.
  /// DELETE /api/projects/{name}/activities/{id}/local
  Future<void> deleteLocalActivity(ProjectRef ref, int activityId) async {
    await api.delete(ref.path('/activities/$activityId/local'));
  }

  /// POST /api/projects/{name}/activities/{id}/refresh
  ///
  /// Returns immediately with 202 `{refresh_status: pending}` — the Strava
  /// re-fetch runs server-side as a background job (issue #148). Callers poll
  /// `/meta` for the verdict; the default 30 s timeout is plenty for the
  /// trigger, which makes no network calls of its own.
  Future<Map<String, dynamic>> refreshActivity(
    ProjectRef ref,
    int activityId,
  ) async {
    final data = await api.post(
      ref.path('/activities/$activityId/refresh'),
      {},
    );
    return (data as Map?)?.cast<String, dynamic>() ??
        {'refresh_status': 'pending'};
  }

  /// POST /api/projects/{name}/segments/{segId}/resolve-route
  ///
  /// [force] bypasses the server's guard against silently discarding a
  /// manually edited route (issue #150) — pass it only after the caller has
  /// confirmed with the user.
  Future<Map<String, dynamic>> resolveTrainRoute(
    ProjectRef ref,
    String segId, {
    String? hafasProvider,
    String? trainNumber,
    String? date,
    bool force = false,
  }) async {
    final sid = Uri.encodeComponent(segId);
    final body = <String, dynamic>{
      if (hafasProvider != null && hafasProvider.isNotEmpty)
        'hafas_provider': hafasProvider,
      if (trainNumber != null && trainNumber.isNotEmpty)
        'train_number': trainNumber,
      if (date != null && date.isNotEmpty) 'date': date,
      if (force) 'force': true,
    };
    final data = await api.post(
      ref.path('/segments/$sid/resolve-route'),
      body,
      timeout: const Duration(minutes: 3),
    );
    return data as Map<String, dynamic>;
  }

  /// Replace a segment's route geometry with a manually edited point list.
  /// PUT /api/projects/{name}/segments/{segId}/track
  /// [payload] is [TrackEditModel.toSavePayload]. Returns the updated segment
  /// route fields (`route_polyline`/`route_mode`/`route_status`/`route_edited`).
  Future<Map<String, dynamic>> saveSegmentTrack(
    ProjectRef ref,
    String segId,
    Map<String, dynamic> payload,
  ) async {
    final sid = Uri.encodeComponent(segId);
    final data = await api.put(ref.path('/segments/$sid/track'), payload);
    return data as Map<String, dynamic>;
  }
}
