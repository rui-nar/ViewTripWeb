/// Base HTTP client for the ViewTrip REST API.
///
/// Stores the JWT returned by /api/auth/token or /api/auth/google
/// and attaches it as a Bearer token on every request.
library;

import 'dart:convert';
import 'package:http/http.dart' as http;

// Empty string → relative URLs (same origin, production).
// Override at build time: --dart-define=API_BASE_URL=http://localhost:8000
const _kApiBaseUrl = String.fromEnvironment('API_BASE_URL');

class ApiClient {
  final String baseUrl;
  final http.Client _client;
  String? _token;

  // httpClient is injectable so tests can supply a MockClient
  // (package:http/testing.dart); production uses the default.
  ApiClient({this.baseUrl = _kApiBaseUrl, http.Client? httpClient})
      : _client = httpClient ?? http.Client();

  void setToken(String token) => _token = token;
  void clearToken() => _token = null;
  bool get isAuthenticated => _token != null;

  /// Exposes the current JWT for multipart upload requests built outside
  /// this class (e.g. ProjectsNotifier on web where dart:io is unavailable).
  String? get tokenForUpload => _token;

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (_token != null) 'Authorization': 'Bearer $_token',
  };

  static const _kDefaultTimeout = Duration(seconds: 30);

  Future<dynamic> get(String path, {Duration timeout = _kDefaultTimeout}) async {
    final res = await _client
        .get(Uri.parse('$baseUrl$path'), headers: _headers)
        .timeout(timeout);
    return _handle(res);
  }

  Future<dynamic> post(
    String path,
    Map<String, dynamic> body, {
    Duration timeout = _kDefaultTimeout,
  }) async {
    final res = await _client
        .post(
          Uri.parse('$baseUrl$path'),
          headers: _headers,
          body: jsonEncode(body),
        )
        .timeout(timeout);
    return _handle(res);
  }

  Future<dynamic> put(String path, Map<String, dynamic> body, {Duration timeout = _kDefaultTimeout}) async {
    final res = await _client
        .put(
          Uri.parse('$baseUrl$path'),
          headers: _headers,
          body: jsonEncode(body),
        )
        .timeout(timeout);
    return _handle(res);
  }

  Future<dynamic> delete(String path, {Duration timeout = _kDefaultTimeout}) async {
    final res = await _client
        .delete(Uri.parse('$baseUrl$path'), headers: _headers)
        .timeout(timeout);
    return _handle(res);
  }

  /// Fetch a binary resource and return the raw response.
  /// Use this for file downloads where the body is not JSON.
  Future<http.Response> getRaw(String path) async {
    final res = await _client.get(Uri.parse('$baseUrl$path'), headers: _headers);
    if (res.statusCode >= 200 && res.statusCode < 300) return res;
    throw ApiException(res.statusCode, res.body);
  }

  dynamic _handle(http.Response res) {
    if (res.statusCode >= 200 && res.statusCode < 300) {
      if (res.body.isEmpty) return null;
      return jsonDecode(res.body);
    }
    throw ApiException(res.statusCode, res.body);
  }
}

class ApiException implements Exception {
  final int statusCode;
  final String body;
  ApiException(this.statusCode, this.body);

  @override
  String toString() => 'ApiException($statusCode): $body';
}

/// Singleton instance shared across the app.
final api = ApiClient();
