import 'package:flutter/foundation.dart';
import '../api/client.dart';
import '../crypto/encryption.dart';
import '../projects/photo_thumb_cache.dart';
import '../projects/project_data_cache.dart';
import 'auth_service.dart';

// ── User model ─────────────────────────────────────────────────────────────────

class User {
  final String id;
  final String email;
  final String displayName;
  final String avatarUrl;
  final String authProvider; // "local" | "google"
  final bool isAdmin;

  /// Whether the account's email address has been confirmed (issue #110).
  /// Gates sending invite mail and being matched to a pending invite.
  final bool emailVerified;
  final bool passwordChangeRequired;

  const User({
    required this.id,
    required this.email,
    required this.displayName,
    required this.avatarUrl,
    required this.authProvider,
    this.isAdmin = false,
    this.emailVerified = false,
    this.passwordChangeRequired = false,
  });

  factory User.fromMap(Map<String, dynamic> map) => User(
        id: map['id']?.toString() ?? '',
        email: map['email'] as String? ?? '',
        displayName: map['display_name'] as String? ?? '',
        avatarUrl: map['avatar_url'] as String? ?? '',
        authProvider: map['auth_provider'] as String? ?? 'local',
        isAdmin: map['is_admin'] == true,
        emailVerified: map['email_verified'] == true,
        passwordChangeRequired: map['password_change_required'] == true,
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
  bool _isRestoring = false;
  String? _error;

  AuthNotifier(this._service);

  User? get user => _user;
  bool get isLoading => _isLoading;

  /// Keeps [projectDataCache] scoped to whoever is currently signed in —
  /// every codepath that changes [_user] eventually calls [notifyListeners],
  /// so hooking it here covers login/restore/register/profile-refresh
  /// without a separate call at each of those sites. Idempotent/cheap when
  /// the user hasn't actually changed.
  @override
  void notifyListeners() {
    final idStr = _user?.id;
    projectDataCache.setCurrentUser(
        (idStr == null || idStr.isEmpty) ? null : int.tryParse(idStr));
    super.notifyListeners();
  }

  /// True only while [init] restores a persisted session at app start.
  ///
  /// [isLoading] cannot stand in for this: it is also raised by an interactive
  /// sign-in, and SplashGate keys the brand splash off this flag — it must not
  /// come back over the login form once the app is up.
  bool get isRestoring => _isRestoring;
  String? get error => _error;

  /// Restores a persisted session on app start.
  /// Call via `..init()` cascade in Provider `create`.
  Future<void> init() async {
    _isLoading = true;
    _isRestoring = true;
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
      _isRestoring = false;
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

  /// [email] is the login identifier as well as the address the account is
  /// reachable at (issue #110). [firstName] / [lastName] become the display
  /// name server-side.
  Future<void> register(
    String email,
    String password, {
    required String firstName,
    required String lastName,
  }) async {
    _setLoading(true);
    try {
      final map = await _service.register(
        email,
        password,
        firstName: firstName,
        lastName: lastName,
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
    // Full wipe, not just a rescope: a signed-out device must not keep
    // another account's cached trip data sitting on disk.
    await projectDataCache.clearAll();
    await photoThumbCache.clearAll();
    notifyListeners();
  }

  /// After a successful login/restore, try to unlock encryption on this trusted
  /// device. Harmless no-op when encryption is disabled or this device isn't
  /// approved yet (those fall through to device approval / recovery). Never throws.
  Future<void> _unlockEncryption() async {
    try {
      await encryption.prepareForSession();
    } catch (_) {}
  }

  /// Update the in-memory user from a token-response `user` map.
  void updateUser(Map<String, dynamic> userMap) {
    _user = User.fromMap(userMap);
    notifyListeners();
  }

  /// Re-fetch the profile from the server (e.g. after a forced password change
  /// clears `password_change_required`), so redirects re-evaluate.
  Future<void> refreshProfile() async {
    try {
      _user = User.fromMap(await _service.getMe());
      notifyListeners();
    } catch (_) {}
  }

  /// Consume an emailed verification token (issue #110), then refresh the
  /// profile so the "verify your email" banner clears without a re-login.
  /// Rethrows so the screen can show why a link failed.
  Future<void> verifyEmail(String token) async {
    await _service.verifyEmail(token);
    if (_user != null) await refreshProfile();
  }

  /// Request a fresh verification email. Rethrows [ApiException] so the caller
  /// can distinguish a 429 (too many requests) from a network failure.
  Future<void> resendVerification() => _service.resendVerification();

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
