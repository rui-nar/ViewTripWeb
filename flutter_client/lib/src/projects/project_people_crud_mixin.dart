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
  List<Map<String, dynamic>> get groups;
  set groups(List<Map<String, dynamic>> v);
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
    String? notes,
    List<Map<String, String>>? socials,
    List<String>? nationalities,
    String? residence,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return null;
    try {
      final res = await api.post('/api/people/', {
        'project_name': projectName,
        if (name != null) 'name': name,
        if (email != null) 'email': email,
        if (phone != null) 'phone': phone,
        if (notes != null) 'notes': notes,
        if (socials != null) 'socials': socials,
        if (nationalities != null) 'nationalities': nationalities,
        if (residence != null) 'residence': residence,
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
    String? notes,
    List<Map<String, String>>? socials,
    List<String>? nationalities,
    String? residence,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    try {
      await api.put('/api/people/$personId', {
        'name': name,
        'email': email,
        'phone': phone,
        'notes': notes,
        'socials': socials,
        'nationalities': nationalities,
        'residence': residence,
      });
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  /// City autocomplete for the residence field — proxied through the server's
  /// Nominatim endpoint. Returns [] on failure or a too-short query.
  Future<List<String>> searchPlaces(String query) async {
    final q = query.trim();
    if (q.length < 2) return [];
    try {
      final res = await api.get('/api/geo/places?q=${Uri.encodeQueryComponent(q)}');
      return (res as List).cast<String>();
    } on Exception {
      return [];
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

  /// Create an encounter with a person OR a group met (issue #56 — caller
  /// guarantees exactly one of [personId]/[groupId] is set).
  Future<void> createEncounter({
    int? personId,
    int? groupId,
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
        'group_id': groupId,
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
        'group_id': groupId,
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

  /// Update an encounter's person/group, date, place, or note (issue #56 —
  /// caller guarantees exactly one of [personId]/[groupId] is set).
  Future<void> updateEncounter(
    String encounterId, {
    int? personId,
    int? groupId,
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
        'group_id': groupId,
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

  // ── Polarsteps: view a person's shared trip (#40 follow-up) ─────────────────
  // View-only overlay: steps of a followed person's trip, fetched on demand and
  // rendered on the manage map. Never persisted into the project.

  /// Step points of the currently-displayed Polarsteps trip overlay (each with
  /// `lat`/`lon`/`date`/`name`), or empty when no overlay is shown.
  List<Map<String, dynamic>> polarstepsOverlaySteps = [];

  /// Label for the current overlay (e.g. "Alice · Asia 2024"), or null.
  String? polarstepsOverlayLabel;

  /// Fetch a person's shared Polarsteps trips. Returns null on failure (error set).
  Future<List<Map<String, dynamic>>?> fetchPersonPolarstepsTrips(
      int personId) async {
    try {
      final res = await api.get('/api/people/$personId/polarsteps/trips');
      return (res as List).cast<Map<String, dynamic>>();
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
      return null;
    }
  }

  /// Load one trip's steps and show it as the map overlay. Returns false on failure.
  Future<bool> showPersonPolarstepsTrip(
      int personId, int tripId, String label) async {
    try {
      final res =
          await api.get('/api/people/$personId/polarsteps/trips/$tripId/steps');
      final steps = (res as List)
          .cast<Map<String, dynamic>>()
          .where((s) => s['lat'] != null && s['lon'] != null)
          .toList();
      polarstepsOverlaySteps = steps;
      polarstepsOverlayLabel = label;
      notifyListeners();
      return true;
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
      return false;
    }
  }

  void clearPolarstepsOverlay() {
    if (polarstepsOverlaySteps.isEmpty && polarstepsOverlayLabel == null) return;
    polarstepsOverlaySteps = [];
    polarstepsOverlayLabel = null;
    notifyListeners();
  }

  // ── Group CRUD (issue #50) ──────────────────────────────────────────────────

  /// Create a group; returns the new id, or null on failure.
  Future<int?> createGroup({
    String? name,
    List<String>? nationalities,
    List<Map<String, String>>? socials,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return null;
    try {
      final res = await api.post('/api/groups/', {
        'project_name': projectName,
        if (name != null) 'name': name,
        if (nationalities != null) 'nationalities': nationalities,
        if (socials != null) 'socials': socials,
      });
      await reloadDetailsOnly(projectName);
      return (res as Map)['id'] as int?;
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
      return null;
    }
  }

  Future<void> updateGroup(
    int groupId, {
    String? name,
    List<String>? nationalities,
    List<Map<String, String>>? socials,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    try {
      await api.put('/api/groups/$groupId', {
        'name': name,
        'nationalities': nationalities,
        'socials': socials,
      });
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  Future<void> deleteGroup(int groupId) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    // Optimistic: drop the group, its direct group-encounters (issue #56 —
    // unlike a member, they have no fallback), and ungroup remaining members.
    groups = groups.where((g) => g['id'] != groupId).toList();
    items = items
        .where((it) => !(it['item_type'] == 'encounter' &&
            it['encounter']?['group_id'] == groupId))
        .toList();
    for (final p in people) {
      if (p['group_id'] == groupId) p['group_id'] = null;
    }
    notifyListeners();
    try {
      await api.delete('/api/groups/$groupId');
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  /// Set the group's member list to exactly [personIds] (assigns them, clears others).
  Future<void> setGroupMembers(int groupId, List<int> personIds) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    try {
      await api.put('/api/groups/$groupId/members', {'person_ids': personIds});
      await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  /// Fetch a group with its members (id, name, avatar).
  Future<Map<String, dynamic>?> fetchGroup(int groupId) async {
    try {
      final res = await api.get('/api/groups/$groupId');
      return (res as Map).cast<String, dynamic>();
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
      return null;
    }
  }
}
