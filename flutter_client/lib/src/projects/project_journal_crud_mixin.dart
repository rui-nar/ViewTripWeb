/// Mixin providing Journal Entry CRUD operations to ProjectNotifier.
library;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../api/client.dart';
import '../core/project_ref.dart';
import '../crypto/encryption.dart';
import 'project_quota_mixin.dart';

/// Monotonic counter backing createJournal's optimistic placeholder ids — a
/// counter (rather than a timestamp alone) guarantees two concurrent creates
/// never collide even if they land in the same clock tick.
int _optimisticJournalIdCounter = 0;

mixin ProjectJournalCrudMixin on ChangeNotifier, ProjectQuotaMixin {
  // ── Abstract: project state (satisfied by ProjectNotifier fields) ─────────
  ProjectRef? get projectRef;
  List<Map<String, dynamic>> get items;
  set items(List<Map<String, dynamic>> v);
  String? get error;
  set error(String? v);

  Future<void> reloadDetailsOnly(ProjectRef ref);
  String errorMessage(Exception e);

  // ── Journal CRUD ──────────────────────────────────────────────────────────

  /// Creates a journal entry. Returns `true` on success, `false` on failure
  /// (in which case the optimistic placeholder is rolled back and [error] is
  /// set) — callers must check this before treating the save as done.
  Future<bool> createJournal({
    required String date,
    required String geoMode,
    String? time,
    String? description,
    double? lat,
    double? lon,
    int? insertAfterIndex,
  }) async {
    final ref = projectRef;
    if (ref == null) return false;
    // Unique per call so two concurrent creates never share a placeholder id
    // (a literal '__optimistic__' would collide and produce duplicate
    // ValueKeys in the map marker layer).
    final tempId = 'optimistic-${_optimisticJournalIdCounter++}';
    final placeholder = {
      'item_type': 'journal',
      'journal': {
        'id': tempId,
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
      final encDescription = await encryption.protect(description);
      await api.post(ref.withOwner('/api/journal/'), {
        'project_name': ref.name,
        'date': date,
        'geo_mode': geoMode,
        if (time != null) 'time': time,
        if (encDescription != null) 'description': encDescription,
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
        if (insertAfterIndex != null) 'insert_after_index': insertAfterIndex,
      });
      await reloadDetailsOnly(ref);
      return true;
    } on Exception catch (e) {
      // Roll back the placeholder so a failed create leaves no phantom item.
      items = items
          .where((item) =>
              !(item['item_type'] == 'journal' &&
                item['journal']?['id']?.toString() == tempId))
          .toList();
      error = errorMessage(e);
      notifyListeners();
      return false;
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
    final ref = projectRef;
    if (ref == null) return;
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
      final encDescription = await encryption.protect(description);
      await api.put('/api/journal/$journalId', {
        'date': date,
        'geo_mode': geoMode,
        if (time != null) 'time': time,
        if (encDescription != null) 'description': encDescription,
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
      });
      await reloadDetailsOnly(ref);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  void removeJournalLocally(String journalId) {
    items = items
        .where((item) =>
            !(item['item_type'] == 'journal' &&
              item['journal']?['id']?.toString() == journalId))
        .toList();
    notifyListeners();
  }

  Future<void> deleteJournal(String journalId) async {
    final ref = projectRef;
    if (ref == null) return;
    items.removeWhere((item) =>
        item['item_type'] == 'journal' &&
        item['journal']?['id']?.toString() == journalId);
    notifyListeners();
    try {
      await api.delete('/api/journal/$journalId');
      await reloadDetailsOnly(ref);
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
      // A plan limit (issue #121) must not vanish into this null — record it so
      // the dialog can offer an upgrade instead of dropping the photo silently.
      recordQuotaRefusal(res.statusCode, res.body);
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
    final ref = projectRef;
    try {
      await api.delete('/api/journal/$journalId/photos/$photoUuid');
      if (reload && ref != null) await reloadDetailsOnly(ref);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }
}
