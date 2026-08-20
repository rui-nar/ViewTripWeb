/// Persists a self-hosted server URL override (login screen's "Self-hosting?"
/// link), for native mobile builds that can't take --dart-define=API_BASE_URL
/// at build time the way a self-hosted web/Docker deployment can.
library;

import 'package:shared_preferences/shared_preferences.dart';

const _kCustomServerUrlKey = 'custom_server_url';

/// The saved override, or null if the app is using its built-in default.
Future<String?> readCustomServerUrl() async {
  final prefs = await SharedPreferences.getInstance();
  final url = prefs.getString(_kCustomServerUrlKey);
  return (url == null || url.isEmpty) ? null : url;
}

/// Saves [url] as the server override, or clears it when [url] is null/empty.
/// Strips a trailing slash so it composes cleanly with ApiClient's
/// '$baseUrl$path' concatenation.
Future<void> writeCustomServerUrl(String? url) async {
  final prefs = await SharedPreferences.getInstance();
  final trimmed = url?.trim();
  if (trimmed == null || trimmed.isEmpty) {
    await prefs.remove(_kCustomServerUrlKey);
    return;
  }
  final normalised =
      trimmed.endsWith('/') ? trimmed.substring(0, trimmed.length - 1) : trimmed;
  await prefs.setString(_kCustomServerUrlKey, normalised);
}

/// Whether [url] is an acceptable server URL: http(s):// followed by a host.
bool isValidServerUrl(String url) =>
    RegExp(r'^https?://[^\s/]+').hasMatch(url.trim());
