/// Single-project service — wraps /api/projects/{name} and /api/geo/* endpoints.
library;

import 'package:flutter/foundation.dart' show visibleForTesting;

import '../api/client.dart';
import '../map/polyline_decoder.dart';

class ProjectService {
  /// Fetches the full project dict for [name] including elevation_profile data.
  /// GET /api/projects/{name}
  Future<Map<String, dynamic>> getDetails(String name) async {
    final data = await api.get('/api/projects/$name');
    return data as Map<String, dynamic>;
  }

  /// Lightweight project dict — no elevation_profile or summary_polyline.
  /// Typically 10-15× smaller than getDetails(); use for initial load and
  /// reloads that don't need the elevation chart to update.
  /// GET /api/projects/{name}/meta
  Future<Map<String, dynamic>> getDetailsMeta(String name) async {
    final data = await api.get('/api/projects/$name/meta');
    return data as Map<String, dynamic>;
  }

  /// Fetches the GeoJSON FeatureCollection for [name].
  /// GET /api/geo/project?name={name}
  ///
  /// The full-res endpoint sends activity tracks as Google-encoded polylines
  /// (in `properties.polyline`, with empty `coordinates`) to keep the payload
  /// small; [_expandEncodedActivities] decodes them back to `coordinates` so
  /// the rest of the app sees standard GeoJSON. The timeout is generous because
  /// a cold-cache build of a large trip can take a while on NAS storage.
  Future<Map<String, dynamic>> getGeo(String name) async {
    final encoded = Uri.encodeComponent(name);
    // encoded=1 opts into the compact payload (activity tracks as Google-encoded
    // polylines); expandEncodedActivities decodes them back to coordinates.
    final data = await api.get('/api/geo/project?name=$encoded&encoded=1',
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
      final pts = decodePolyline(enc);
      geom['coordinates'] = [for (final p in pts) [p.lon, p.lat]];
    }
    return geo;
  }

  /// Fetches pre-computed low-res GeoJSON (straight lines per activity) for [name].
  /// GET /api/geo/project/low-res?name={name}
  Future<Map<String, dynamic>> getLowResGeo(String name) async {
    final encoded = Uri.encodeComponent(name);
    final data = await api.get('/api/geo/project/low-res?name=$encoded');
    return data as Map<String, dynamic>;
  }

  /// Fetches pre-computed project statistics for [name].
  /// Pass [tags] to filter stats to only days with matching tags.
  /// GET /api/projects/{name}/stats[?tags=x&tags=y]
  Future<Map<String, dynamic>> getStats(String name,
      {List<String> tags = const []}) async {
    final encoded = Uri.encodeComponent(name);
    final query = tags.isEmpty
        ? ''
        : '?${tags.map((t) => 'tags=${Uri.encodeComponent(t)}').join('&')}';
    final data = await api.get('/api/projects/$encoded/stats$query');
    return data as Map<String, dynamic>;
  }

  /// PUT /api/projects/{name}/track-style
  Future<void> saveTrackStyle(
    String name, {
    String? trackColor,
    Object? trackSecondaryColor = _kUnset, // null = clear, _kUnset = don't send
    double? trackWidth,
    bool? alternating,
    Object? elevationChartColor = _kUnset, // null = clear, _kUnset = don't send
    bool? elevationChartShowLine,
  }) async {
    final enc = Uri.encodeComponent(name);
    await api.put('/api/projects/$enc/track-style', {
      if (trackColor != null) 'track_color': trackColor,
      if (trackSecondaryColor != _kUnset) 'track_secondary_color': trackSecondaryColor,
      if (trackWidth != null) 'track_width': trackWidth,
      if (alternating != null) 'alternating_track_colors': alternating,
      if (elevationChartColor != _kUnset) 'elevation_chart_color': elevationChartColor,
      if (elevationChartShowLine != null) 'elevation_chart_show_line': elevationChartShowLine,
    });
  }

  static const Object _kUnset = Object();

  /// PUT /api/projects/{name}/items/sort
  Future<void> sortItems(String name) async {
    final enc = Uri.encodeComponent(name);
    await api.put('/api/projects/$enc/items/sort', {});
  }

  /// PUT /api/projects/{name}/languages
  Future<void> saveLanguages(String name, List<String> languages) async {
    final enc = Uri.encodeComponent(name);
    await api.put('/api/projects/$enc/languages', {'languages': languages});
  }

  /// POST /api/projects/{name}/segments/{segId}/resolve-route
  Future<Map<String, dynamic>> resolveTrainRoute(
    String projectName,
    String segId, {
    String? hafasProvider,
    String? trainNumber,
    String? date,
  }) async {
    final enc = Uri.encodeComponent(projectName);
    final sid = Uri.encodeComponent(segId);
    final body = <String, dynamic>{
      if (hafasProvider != null && hafasProvider.isNotEmpty)
        'hafas_provider': hafasProvider,
      if (trainNumber != null && trainNumber.isNotEmpty)
        'train_number': trainNumber,
      if (date != null && date.isNotEmpty) 'date': date,
    };
    final data = await api.post(
      '/api/projects/$enc/segments/$sid/resolve-route',
      body,
      timeout: const Duration(minutes: 3),
    );
    return data as Map<String, dynamic>;
  }
}
