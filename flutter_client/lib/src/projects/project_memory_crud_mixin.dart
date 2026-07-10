/// Mixin providing Memory CRUD operations to ProjectNotifier.
///
/// Depends on abstract members satisfied by ProjectNotifier's fields and
/// two thin public delegates (reloadDetailsOnly, errorMessage) that
/// forward to the private helpers in the notifier's library.
library;

import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;

import '../api/client.dart';
import '../crypto/encryption.dart';

mixin ProjectMemoryCrudMixin on ChangeNotifier {
  // ── Abstract: project state (satisfied by ProjectNotifier fields) ─────────
  String? get projectName;
  List<Map<String, dynamic>> get items;
  set items(List<Map<String, dynamic>> v);
  String? get error;
  set error(String? v);

  /// Details-only reload — thin delegate to the private helper in the notifier.
  Future<void> reloadDetailsOnly(String name);

  /// Formats an Exception into a user-readable string — delegates to _msg.
  String errorMessage(Exception e);

  // ── Memory CRUD ───────────────────────────────────────────────────────────

  Future<void> createMemory({
    required String date,
    required String geoMode,
    String? name,
    String? time,
    String? description,
    double? lat,
    double? lon,
    int? insertAfterIndex,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    final placeholder = {
      'item_type': 'memory',
      'memory': {
        'id': '__optimistic__',
        'name': name,
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
      final encName = await encryption.protect(name);
      final encDescription = await encryption.protect(description);
      await api.post('/api/memories/', {
        'project_name': projectName,
        'date': date,
        'geo_mode': geoMode,
        if (encName != null) 'name': encName,
        if (time != null) 'time': time,
        if (encDescription != null) 'description': encDescription,
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

  Future<void> updateMemory(
    String memoryId, {
    required String date,
    required String geoMode,
    String? name,
    String? time,
    String? description,
    double? lat,
    double? lon,
  }) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    for (final item in items) {
      if (item['item_type'] == 'memory' &&
          item['memory']?['id']?.toString() == memoryId) {
        final mem = Map<String, dynamic>.from(item['memory'] as Map);
        mem['name'] = name;
        mem['date'] = date;
        mem['time'] = time;
        mem['description'] = description;
        mem['geo_mode'] = geoMode;
        mem['lat'] = lat;
        mem['lon'] = lon;
        item['memory'] = mem;
        break;
      }
    }
    notifyListeners();
    try {
      final encName = await encryption.protect(name);
      final encDescription = await encryption.protect(description);
      await api.put('/api/memories/$memoryId', {
        'date': date,
        'geo_mode': geoMode,
        if (encName != null) 'name': encName,
        if (time != null) 'time': time,
        if (encDescription != null) 'description': encDescription,
        if (lat != null) 'lat': lat,
        if (lon != null) 'lon': lon,
      });
      // No reload needed — optimistic update already applied above.
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  void removeMemoryLocally(String memoryId) {
    items = items
        .where((item) =>
            !(item['item_type'] == 'memory' &&
              item['memory']?['id']?.toString() == memoryId))
        .toList();
    notifyListeners();
  }

  Future<void> deleteMemory(String memoryId) async {
    final projectName = this.projectName;
    if (projectName == null) return;
    items.removeWhere((item) =>
        item['item_type'] == 'memory' &&
        item['memory']?['id']?.toString() == memoryId);
    notifyListeners();
    try {
      await api.delete('/api/memories/$memoryId');
      // No reload needed — memory already removed locally above.
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  /// Upload a photo for a memory. Returns the UUID string on success.
  Future<String?> uploadMemoryPhoto(
    String memoryId,
    Uint8List bytes,
    String filename,
  ) async {
    final token = api.tokenForUpload;
    if (token == null) return null;
    final uri = Uri.parse('${api.baseUrl}/api/memories/$memoryId/photos');
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

  Future<void> deleteMemoryPhoto(
    String memoryId,
    String photoUuid, {
    bool reload = true,
  }) async {
    final projectName = this.projectName;
    try {
      await api.delete('/api/memories/$memoryId/photos/$photoUuid');
      if (reload && projectName != null) await reloadDetailsOnly(projectName);
    } on Exception catch (e) {
      error = errorMessage(e);
      notifyListeners();
    }
  }

  // ── Comments ────────────────────────────────────────────────────────────────

  Future<List<Map<String, dynamic>>> fetchComments(String memoryId) async {
    final data = await api.get('/api/memories/$memoryId/comments');
    return (data as List).cast<Map<String, dynamic>>();
  }

  Future<void> addComment(
    String memoryId,
    String text, {
    int? parentCommentId,
  }) async {
    await api.post('/api/memories/$memoryId/comments', {
      'text': text,
      if (parentCommentId != null) 'parent_comment_id': parentCommentId,
    });
  }

  Future<void> deleteComment(String memoryId, int commentId) async {
    await api.delete('/api/memories/$memoryId/comments/$commentId');
  }

  // ── Likes ───────────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> fetchLikes(String memoryId) async {
    final data = await api.get('/api/memories/$memoryId/likes');
    return data as Map<String, dynamic>;
  }

  Future<void> likeMemory(String memoryId) async {
    await api.post('/api/memories/$memoryId/like', {});
  }

  Future<void> unlikeMemory(String memoryId) async {
    await api.delete('/api/memories/$memoryId/like');
  }

  // ── Translations ─────────────────────────────────────────────────────────────

  Future<Map<String, dynamic>> fetchTranslation(
    String memoryId,
    String langCode,
  ) async {
    // When encryption is on, the server only holds ciphertext and cannot
    // translate it (#26/#27). Don't send ciphertext to the translator — surface
    // a clear "unavailable" instead. (UI shows the graceful error message.)
    if (encryption.isUnlocked) {
      throw Exception('Translation is unavailable for encrypted memories');
    }
    final data = await api.get('/api/memories/$memoryId/translations/$langCode');
    return data as Map<String, dynamic>;
  }
}
