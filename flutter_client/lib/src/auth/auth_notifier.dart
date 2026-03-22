import 'package:flutter/foundation.dart';
import 'auth_service.dart';

// ── User model ─────────────────────────────────────────────────────────────────

class User {
  final String id;
  final String email;
  final String displayName;
  final String avatarUrl;
  final String authProvider; // "local" | "google"

  const User({
    required this.id,
    required this.email,
    required this.displayName,
    required this.avatarUrl,
    required this.authProvider,
  });

  factory User.fromMap(Map<String, dynamic> map) => User(
        id: map['id']?.toString() ?? '',
        email: map['email'] as String? ?? '',
        displayName: map['display_name'] as String? ?? '',
        avatarUrl: map['avatar_url'] as String? ?? '',
        authProvider: map['auth_provider'] as String? ?? 'local',
      );

  /// Sentinel used after restoring a session from secure storage when no
  /// /api/auth/me endpoint is available yet to fetch the full profile.
  static const restored = User(
    id: '',
    email: '',
    displayName: '',
    avatarUrl: '',
    authProvider: 'local',
  );
}

// ── AuthNotifier ───────────────────────────────────────────────────────────────

class AuthNotifier extends ChangeNotifier {
  final AuthService _service;

  User? _user;
  bool _isLoading = false;
  String? _error;

  AuthNotifier(this._service);

  User? get user => _user;
  bool get isLoading => _isLoading;
  String? get error => _error;

  /// Restores a persisted session on app start.
  /// Call via `..init()` cascade in Provider `create`.
  Future<void> init() async {
    _isLoading = true;
    notifyListeners();
    try {
      final restored = await _service.restoreSession();
      if (restored) {
        // Token restored — attempt to fetch the real profile from the server.
        // Fall back to the sentinel user if the network is unavailable so the
        // session is still considered valid offline.
        try {
          final data = await _service.getMe();
          _user = User.fromMap(data);
        } catch (_) {
          _user = User.restored;
        }
      } else {
        _user = null;
      }
    } catch (_) {
      _user = null;
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> loginWithPassword(String email, String password) async {
    _setLoading(true);
    try {
      final map = await _service.loginWithPassword(email, password);
      _user = User.fromMap(map);
      _error = null;
    } on Exception catch (e) {
      _error = _extractMessage(e);
      _user = null;
    } finally {
      _setLoading(false);
    }
  }

  Future<void> loginWithGoogle(String idToken) async {
    _setLoading(true);
    try {
      final map = await _service.loginWithGoogle(idToken);
      _user = User.fromMap(map);
      _error = null;
    } on Exception catch (e) {
      _error = _extractMessage(e);
      _user = null;
    } finally {
      _setLoading(false);
    }
  }

  Future<void> register(
    String username,
    String password, {
    String displayName = '',
    String email = '',
  }) async {
    _setLoading(true);
    try {
      final map = await _service.register(
        username,
        password,
        displayName: displayName,
        email: email,
      );
      _user = User.fromMap(map);
      _error = null;
    } on Exception catch (e) {
      _error = _extractMessage(e);
      _user = null;
    } finally {
      _setLoading(false);
    }
  }

  Future<void> logout() async {
    await _service.logout();
    _user = null;
    _error = null;
    notifyListeners();
  }

  void clearError() {
    _error = null;
    notifyListeners();
  }

  // ── helpers ──────────────────────────────────────────────────────────────────

  void _setLoading(bool v) {
    _isLoading = v;
    notifyListeners();
  }

  /// Extracts the FastAPI `"detail"` string from an ApiException body, falling
  /// back to the raw exception message.
  String _extractMessage(Exception e) {
    final s = e.toString();
    final match = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
    if (match != null) return match.group(1)!;
    return s.replaceFirst('Exception: ', '');
  }
}
