library;

import '../api/client.dart';

class SettingsService {
  Future<Map<String, dynamic>> getProfile() async =>
      await api.get('/api/auth/me') as Map<String, dynamic>;

  Future<({String? token, Map<String, dynamic> user})> updateProfile(
      String displayName) async {
    try {
      final data = await api.put('/api/auth/me', {'display_name': displayName})
          as Map<String, dynamic>;
      return (
        token: data['access_token'] as String?,
        user: data['user'] as Map<String, dynamic>? ?? {},
      );
    } on ApiException catch (e) {
      throw Exception(_detail(e.body));
    }
  }

  Future<void> changePassword({
    required String current,
    required String next,
  }) async {
    try {
      await api.post('/api/auth/change-password', {
        'current_password': current,
        'new_password': next,
      });
    } on ApiException catch (e) {
      throw Exception(_detail(e.body));
    }
  }

  Future<void> deleteAccount() async {
    try {
      await api.delete('/api/auth/me');
    } on ApiException catch (e) {
      throw Exception(_detail(e.body));
    }
  }

  Future<bool> getStravaStatus() async {
    final data = await api.get('/api/strava/status') as Map<String, dynamic>;
    return data['connected'] == true;
  }

  Future<String> getStravaConnectUrl() async {
    final data = await api.get('/api/strava/connect') as Map<String, dynamic>;
    return data['url'] as String;
  }

  Future<void> disconnectStrava() async => api.delete('/api/strava/disconnect');

  static String _detail(String body) {
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(body);
    return m?.group(1) ?? body;
  }
}
