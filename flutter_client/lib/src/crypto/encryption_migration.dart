/// One-time migration of a user's EXISTING plaintext memory/journal text to
/// ciphertext when they enable encryption (#26, Phase 7).
///
/// Client-side by necessity (the server can't read the plaintext to encrypt it).
/// Idempotent and resumable: it re-encrypts only fields that are still plaintext
/// (an already-encrypted envelope is left untouched), so a re-run finishes the
/// job after any interruption and never double-encrypts.
library;

import '../api/client.dart';
import 'e2ee_crypto.dart';
import 'encryption_service.dart';

class EncryptionMigration {
  final ApiClient _api;
  final EncryptionService _enc;
  EncryptionMigration(this._api, this._enc);

  /// Encrypt all still-plaintext memory/journal text across every project.
  /// Returns the number of rows updated. No-op if encryption isn't unlocked.
  Future<int> run() async {
    if (!_enc.isUnlocked) return 0;
    var migrated = 0;
    final projects = await _api.get('/api/projects/') as List;
    for (final p in projects) {
      final name = (p as Map)['name'] as String;
      final details = await _api.get(
          '/api/projects/${Uri.encodeComponent(name)}') as Map<String, dynamic>;
      final items = (details['items'] as List?) ?? const [];
      for (final raw in items) {
        final item = raw as Map;
        switch (item['item_type']) {
          case 'memory':
            migrated += await _migrateMemory(item['memory'] as Map?);
          case 'journal':
            migrated += await _migrateJournal(item['journal'] as Map?);
        }
      }
    }
    return migrated;
  }

  bool _isPlain(String? v) =>
      v != null && v.isNotEmpty && !EncryptedField.isEnvelope(v);

  /// Encrypt only if the value is still plaintext; leave envelopes/nulls as-is.
  Future<String?> _protectIfPlain(String? v) async =>
      _isPlain(v) ? await _enc.protect(v) : v;

  Future<int> _migrateMemory(Map? mem) async {
    if (mem == null) return 0;
    final name = mem['name'] as String?;
    final desc = mem['description'] as String?;
    if (!_isPlain(name) && !_isPlain(desc)) return 0;
    await _api.put('/api/memories/${mem['id']}', {
      'date': mem['date'],
      'geo_mode': mem['geo_mode'] ?? 'start_of_day',
      if (name != null) 'name': await _protectIfPlain(name),
      if (mem['time'] != null) 'time': mem['time'],
      if (desc != null) 'description': await _protectIfPlain(desc),
      if (mem['lat'] != null) 'lat': mem['lat'],
      if (mem['lon'] != null) 'lon': mem['lon'],
    });
    return 1;
  }

  Future<int> _migrateJournal(Map? j) async {
    if (j == null) return 0;
    final desc = j['description'] as String?;
    if (!_isPlain(desc)) return 0;
    await _api.put('/api/journal/${j['id']}', {
      'date': j['date'],
      'geo_mode': j['geo_mode'] ?? 'start_of_day',
      if (j['time'] != null) 'time': j['time'],
      if (desc != null) 'description': await _protectIfPlain(desc),
      if (j['lat'] != null) 'lat': j['lat'],
      if (j['lon'] != null) 'lon': j['lon'],
    });
    return 1;
  }
}
