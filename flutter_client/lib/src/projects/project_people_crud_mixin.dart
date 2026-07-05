/// Mixin providing People + Encounter CRUD to ProjectNotifier (issue #40).
library;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../api/client.dart';

mixin ProjectPeopleCrudMixin on ChangeNotifier {
  // ── Abstract: project state (satisfied by ProjectNotifier fields) ─────────
  String? get projectName;
  List<Map<String, dynamic>> get items;
  set items(List<Map<String, dynamic>> v);
  List<Map<String, dynamic>> get people;
  set people(List<Map<String, dynamic>> v);
  String? get error;
  set error(String? v);

  Future<void> reloadDetailsOnly(String name);
  String errorMessage(Exception e);

  // ── People CRUD ───────────────────────────────────────────────────────────

  /// Create a person; returns the new id, or null on failure.
  Future<int?> createPerson({
    String? name,
    String? email,
    String? phone,
    String? polarsteps,
    String? notes,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return null;
    try {
      final res = await api.post('/api/people/', {
        'project_name': projectName,
        if (name != null) 'name': name,
        if (email != null) 'email': email,
        if (phone != null) 'phone': phone,
        if (polarsteps != null) 'polarsteps': polarsteps,
        if (notes != null) 'notes': notes,
      });
      await reloadDetailsOnly(projectName);
      return (res as Map)['id'] as int?;
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
      return null;
    }
  }

  Future<void> updatePerson(
    int personId, {
    String? name,
    String? email,
    String? phone,
    String? polarsteps,
    String? notes,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    try {
      await api.put('/api/people/$personId', {
        'name': name,
        'email': email,
        'phone': phone,
        'polarsteps': polarsteps,
        'notes': notes,
      });
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  Future<void> deletePerson(int personId) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    // Optimistic: drop the person and any of their encounter items.
    people = people.where((p) => p['id'] != personId).toList();
    items = items
        .where((it) => !(it['item_type'] == 'encounter' &&
            it['encounter']?['person_id'] == personId))
        .toList();
    notifyListeners();
    try {
      await api.delete('/api/people/$personId');
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  /// Fetch a person with their encounters (date, place, note).
  Future<Map<String, dynamic>?> fetchPerson(int personId) async {
    try {
      final res = await api.get('/api/people/$personId');
      return (res as Map).cast<String, dynamic>();
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
      return null;
    }
  }

  /// Upload/replace a person's avatar; reloads on success.
  Future<bool> uploadPersonAvatar(
    int personId,
    Uint8List bytes,
    String filename,
  ) async {
    final token = api.tokenForUpload;
    final projectName = this.projectName;
    if (token == null || projectName == null) return false;
    final uri = Uri.parse('${api.baseUrl}/api/people/$personId/avatar');
    final request = http.MultipartRequest('POST', uri)
      ..headers['Authorization'] = 'Bearer $token'
      ..files.add(http.MultipartFile.fromBytes('file', bytes, filename: filename));
    try {
      final streamed = await request.send();
      final res = await http.Response.fromStream(streamed);
      if (res.statusCode >= 200 && res.statusCode < 300) {
        await reloadDetailsOnly(projectName);
        return true;
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  // ── Encounter CRUD ────────────────────────────────────────────────────────

  Future<void> createEncounter({
    required int personId,
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
      'item_type': 'encounter',
      'encounter': {
        'id': '__optimistic__',
        'person_id': personId,
        'date': date,
        'time': time,
        'description': description,
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
      await api.post('/api/encounters/', {
        'project_name': projectName,
        'person_id': personId,
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

  Future<void> updateEncounter(
    String encounterId, {
    required int personId,
    required String date,
    required String geoMode,
    String? time,
    String? description,
    double? lat,
    double? lon,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    try {
      await api.put('/api/encounters/$encounterId', {
        'person_id': personId,
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

  Future<void> deleteEncounter(String encounterId) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    items.removeWhere((item) =>
        item['item_type'] == 'encounter' &&
        item['encounter']?['id']?.toString() == encounterId);
    notifyListeners();
    try {
      await api.delete('/api/encounters/$encounterId');
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }
}
