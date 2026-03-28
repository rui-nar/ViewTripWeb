/// Authentication service — wraps /api/auth/* endpoints.
library;

import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../api/client.dart';

class AuthService {
  static const _tokenKey = 'viewtrip_jwt';
  final _storage = const FlutterSecureStorage();

  /// Restore a persisted token on app start.
  Future<bool> restoreSession() async {
    final token = await _storage.read(key: _tokenKey);
    if (token != null) {
      api.setToken(token);
      return true;
    }
    return false;
  }

  Future<Map<String, dynamic>> loginWithPassword(
      String username, String password) async {
    final data = await api.post('/api/auth/token', {
      'username': username,
      'password': password,
    });
    _persist(data['access_token'] as String);
    return data['user'] as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> loginWithGoogle(String idToken) async {
    final data = await api.post('/api/auth/google', {'id_token': idToken});
    _persist(data['access_token'] as String);
    return data['user'] as Map<String, dynamic>;
  }

  Future<Map<String, dynamic>> register(
    String username,
    String password, {
    String displayName = '',
    String email = '',
  }) async {
    final data = await api.post('/api/auth/register', {
      'username': username,
      'password': password,
      'display_name': displayName,
      if (email.isNotEmpty) 'email': email,
    });
    _persist(data['access_token'] as String);
    return data['user'] as Map<String, dynamic>;
  }

  /// Fetches the current user's profile from the server.
  /// Requires a valid token to already be set on [api].
  Future<Map<String, dynamic>> getMe() async {
    final data = await api.get('/api/auth/me');
    return data as Map<String, dynamic>;
  }

  Future<void> logout() async {
    api.clearToken();
    await _storage.delete(key: _tokenKey);
  }

  /// Persist a token returned by a mid-session API call (e.g. profile update).
  Future<void> persistToken(String token) async => _persist(token);

  void _persist(String token) {
    api.setToken(token);
    _storage.write(key: _tokenKey, value: token);
  }
}
