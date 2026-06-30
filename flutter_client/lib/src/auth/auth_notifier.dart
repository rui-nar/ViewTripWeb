import 'package:flutter/foundation.dart';
import '../api/client.dart';
import '../crypto/encryption.dart';
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
        // A 401 means the token is expired/invalid: clear it and force re-login.
        // Any other error (no network, timeout) keeps the sentinel user so the
        // session remains valid offline.
        try {
          final data = await _service.getMe();
          _user = User.fromMap(data);
          await _unlockEncryption();
        } on ApiException catch (e) {
          if (e.statusCode == 401) {
            await _service.logout();
            _user = null;
          } else {
            _user = User.restored;
          }
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
      await _unlockEncryption();
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
      await _unlockEncryption();
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
      await _unlockEncryption();
    } on Exception catch (e) {
      _error = _extractMessage(e);
      _user = null;
    } finally {
      _setLoading(false);
    }
  }

  Future<void> logout() async {
    await _service.logout();
    encryption.lock();
    _user = null;
    _error = null;
    notifyListeners();
  }

  /// After a successful login/restore, try to unlock encryption on this trusted
  /// device. Harmless no-op when encryption is disabled or this device isn't
  /// approved yet (those fall through to device approval / recovery). Never throws.
  Future<void> _unlockEncryption() async {
    try {
      await encryption.unlock();
    } catch (_) {}
  }

  /// Update the in-memory user from a token-response `user` map.
  void updateUser(Map<String, dynamic> userMap) {
    _user = User.fromMap(userMap);
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
