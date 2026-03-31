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

  /// Fetches pre-computed project statistics for [name].
  /// GET /api/projects/{name}/stats
  Future<Map<String, dynamic>> getStats(String name) async {
    final encoded = Uri.encodeComponent(name);
    final data = await api.get('/api/projects/$encoded/stats');
    return data as Map<String, dynamic>;
  }
}
