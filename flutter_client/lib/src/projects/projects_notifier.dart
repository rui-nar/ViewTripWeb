import 'dart:convert';

import 'package:flutter/foundation.dart' show ChangeNotifier;
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

  /// Step 1 of import: open file picker and return the bytes + suggested name.
  /// Returns null if the user cancels.
  Future<({List<int> bytes, String defaultName})?> pickProjectFile() async {
    final result = await FilePicker.platform.pickFiles(
      type: FileType.custom,
      allowedExtensions: ['gettracks'],
      withData: true,
    );
    if (result == null || result.files.isEmpty) return null;
    final picked = result.files.first;
    final bytes = picked.bytes;
    if (bytes == null) return null;
    final rawName = picked.name;
    final defaultName = rawName.endsWith('.gettracks')
        ? rawName.substring(0, rawName.length - '.gettracks'.length)
        : rawName;
    return (bytes: bytes, defaultName: defaultName);
  }

  /// Step 2 of import: upload [bytes] as project [name].
  /// Returns the saved project name on success, null on failure.
  Future<String?> uploadProjectFile({
    required List<int> bytes,
    required String name,
  }) async {
    _isLoading = true;
    _error = null;
    notifyListeners();
    try {
      final data =
          await _uploadBytes(bytes: bytes, filename: '$name.gettracks');
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

  // ── Error helper ──────────────────────────────────────────────────────────────

  String _msg(Exception e) {
    final s = e.toString();
    final m = RegExp(r'"detail"\s*:\s*"([^"]+)"').firstMatch(s);
    return m?.group(1) ?? s.replaceFirst('Exception: ', '');
  }
}
