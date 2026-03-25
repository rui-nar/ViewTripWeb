import 'dart:convert';

import 'package:flutter/foundation.dart' show kIsWeb, ChangeNotifier;
import 'package:file_picker/file_picker.dart';
import 'package:http/http.dart' as http;

import '../api/client.dart';
import 'projects_service.dart';

class ProjectsNotifier extends ChangeNotifier {
  final ProjectsService _service;

  List<Map<String, dynamic>> _projects = [];
  bool _isLoading = false;
  String? _error;

  ProjectsNotifier(this._service);

  List<Map<String, dynamic>> get projects => List.unmodifiable(_projects);
  bool get isLoading => _isLoading;
  String? get error => _error;

  /// Called by [ChangeNotifierProxyProvider] whenever [AuthNotifier] changes.
  void onAuthChanged(bool isLoggedIn) {
    if (isLoggedIn) {
      load();
    } else {
      _projects = [];
      _error = null;
      notifyListeners();
    }
  }

  Future<void> load() async {
    _isLoading = true;
    _error = null;
    notifyListeners();
    try {
      _projects = await _service.list();
    } on Exception catch (e) {
      _error = _msg(e);
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> delete(String name) async {
    _isLoading = true;
    _error = null;
    notifyListeners();
    try {
      await api.delete('/api/projects/${Uri.encodeComponent(name)}');
      _projects = _projects.where((p) => p['name'] != name).toList();
    } on Exception catch (e) {
      _error = _msg(e);
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  Future<void> create(String name) async {
    if (name.trim().isEmpty) return;
    _isLoading = true;
    _error = null;
    notifyListeners();
    try {
      final project = await _service.create(name.trim());
      _projects = [..._projects, project];
    } on Exception catch (e) {
      _error = _msg(e);
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// Cross-platform file import:
  /// - Web: reads bytes via file_picker (no dart:io) → multipart POST directly
  /// - Native: uses file path → ProjectsService.importFile(File)
  ///
  /// Returns the imported project name on success, or null on cancel/failure.
  Future<String?> importFile() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['gettracks'],
      // Load bytes immediately on web; use path on native.
      withData: kIsWeb,
    );
    if (result == null || result.files.isEmpty) return null;

    final picked = result.files.first;
    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      Map<String, dynamic> data;
      if (kIsWeb) {
        final bytes = picked.bytes;
        if (bytes == null) throw Exception('Could not read file bytes');
        data = await _uploadBytes(bytes: bytes, filename: picked.name);
      } else {
        // Avoid importing dart:io at the top level (breaks web compilation).
        // We use a dynamic import bridge via the service which already imports it.
        data = await _uploadNative(picked.path!);
      }
      // Refresh list after a successful import.
      await load();
      return data['name'] as String?;
    } on Exception catch (e) {
      _error = _msg(e);
      _isLoading = false;
      notifyListeners();
      return null;
    }
  }

  // ── Upload helpers ────────────────────────────────────────────────────────────

  /// Web-safe multipart upload using raw bytes — never touches dart:io.
  Future<Map<String, dynamic>> _uploadBytes({
    required List<int> bytes,
    required String filename,
  }) async {
    final token = api.tokenForUpload;
    final request = http.MultipartRequest(
      'POST',
      Uri.parse('${api.baseUrl}/api/projects/import'),
    );
    if (token != null) {
      request.headers['Authorization'] = 'Bearer $token';
    }
    request.files.add(
      http.MultipartFile.fromBytes('file', bytes, filename: filename),
    );
    final streamed = await request.send();
    final res = await http.Response.fromStream(streamed);
    if (res.statusCode != 201) {
      throw ApiException(res.statusCode, res.body);
    }
    if (res.body.isEmpty) return {};
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  /// Native path-based upload delegated to [ProjectsService].
  /// Called only on Android / iOS — dart:io is safe here at runtime.
  Future<Map<String, dynamic>> _uploadNative(String path) async {
    // Conditional import would be cleaner, but using a simple dynamic
    // evaluation keeps the file platform-agnostic at the library level.
    // The dart:io import lives inside projects_service.dart which is
    // compiled out on web (only this method references it and it is never
    // reached when kIsWeb is true).
    return await _service.importFileByPath(path);
  }

  // ── Error helper ──────────────────────────────────────────────────────────────

  String _msg(Exception e) {
    final s = e.toString();
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
    return m?.group(1) ?? s.replaceFirst('Exception: ', '');
  }
}
