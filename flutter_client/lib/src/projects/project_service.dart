/// Single-project service — wraps /api/projects/{name} and /api/geo/* endpoints.
library;

import '../api/client.dart';

class ProjectService {
  /// Fetches the full project dict for [name].
  /// GET /api/projects/{name}
  Future<Map<String, dynamic>> getDetails(String name) async {
    final data = await api.get('/api/projects/$name');
    return data as Map<String, dynamic>;
  }

  /// Fetches the GeoJSON FeatureCollection for [name].
  /// GET /api/geo/project?name={name}
  Future<Map<String, dynamic>> getGeo(String name) async {
    final encoded = Uri.encodeComponent(name);
    final data = await api.get('/api/geo/project?name=$encoded');
    return data as Map<String, dynamic>;
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
    );
    return data as Map<String, dynamic>;
  }
}
