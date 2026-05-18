/// Mixin providing Journal Entry CRUD operations to ProjectNotifier.
library;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../api/client.dart';

mixin ProjectJournalCrudMixin on ChangeNotifier {
  // ── Abstract: project state (satisfied by ProjectNotifier fields) ─────────
  String? get projectName;
  List<Map<String, dynamic>> get items;
  String? get error;
  set error(String? v);

  Future<void> reloadDetailsOnly(String name);
  String errorMessage(Exception e);

  // ── Journal CRUD ──────────────────────────────────────────────────────────

  Future<void> createJournal({
    required String date,
    required String geoMode,
    String? time,
    String? description,
    double? lat,
    double? lon,
    int? insertAfterIndex,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    final placeholder = {
      'item_type': 'journal',
      'journal': {
        'id': '__optimistic__',
        'date': date,
        'time': time,
        'description': description,
        'photos': <String>[],
        'geo_mode': geoMode,
        'lat': lat,
        'lon': lon,
      },
    };
    final insertAt = insertAfterIndex != null
        ? (insertAfterIndex + 1).clamp(0, items.length)
        : items.length;
    items.insert(insertAt, placeholder);
    notifyListeners();
    try {
      await api.post('/api/journal/', {
        'project_name': projectName,
        'date': date,
        'geo_mode': geoMode,
        if (time != null) 'time': time,
        if (description != null) 'description': description,
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
        if (insertAfterIndex != null) 'insert_after_index': insertAfterIndex,
      });
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  Future<void> updateJournal(
    String journalId, {
    required String date,
    required String geoMode,
    String? time,
    String? description,
    double? lat,
    double? lon,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    for (final item in items) {
      if (item['item_type'] == 'journal' &&
          item['journal']?['id']?.toString() == journalId) {
        final j = Map<String, dynamic>.from(item['journal'] as Map);
        j['date'] = date;
        j['time'] = time;
        j['description'] = description;
        j['geo_mode'] = geoMode;
        j['lat'] = lat;
        j['lon'] = lon;
        item['journal'] = j;
        break;
      }
    }
    notifyListeners();
    try {
      await api.put('/api/journal/$journalId', {
        'date': date,
        'geo_mode': geoMode,
        if (time != null) 'time': time,
        if (description != null) 'description': description,
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
      });
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  Future<void> deleteJournal(String journalId) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    items.removeWhere((item) =>
        item['item_type'] == 'journal' &&
        item['journal']?['id']?.toString() == journalId);
    notifyListeners();
    try {
      await api.delete('/api/journal/$journalId');
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  Future<String?> uploadJournalPhoto(
    String journalId,
    Uint8List bytes,
    String filename,
  ) async {
    final token = api.tokenForUpload;
    if (token == null) return null;
    final uri = Uri.parse('${api.baseUrl}/api/journal/$journalId/photos');
    final request = http.MultipartRequest('POST', uri)
      ..headers['Authorization'] = 'Bearer $token'
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    try {
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      if (res.statusCode >= 200 && res.statusCode < 300) {
        final match = RegExp(r'"uuid"\s*:\s*"([^"]+)"').firstMatch(res.body);
        return match?.group(1);
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  Future<void> deleteJournalPhoto(
    String journalId,
    String photoUuid, {
    bool reload = true,
  }) async {
    final projectName = this.projectName;
    try {
      await api.delete('/api/journal/$journalId/photos/$photoUuid');
      if (reload && projectName != null) await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }
}
