/// sqflite-backed on-device cache backend (Android/iOS/desktop) — the L2
/// layer under `ProjectDataCache`'s in-memory L1, so a project already opened
/// on this device survives an app restart without re-downloading its geo and
/// elevation data. Compiled in only via `project_data_cache.dart`'s
/// conditional import (`if (dart.library.io)`); never reachable from web.
///
/// Every public function here is best-effort: this is a cache, never the
/// source of truth, so any failure to open or use the database (no plugin
/// registered — e.g. a plain `flutter test` VM run with no device backing
/// the platform channel, disk full, corrupt file) degrades to "nothing was
/// cached" rather than throwing. `ProjectDataCache`'s L1 map and the live
/// network are what the app actually depends on; this is purely a speed-up.
library;

import 'dart:convert' show jsonDecode, jsonEncode, utf8;
import 'dart:io' show GZipCodec;
import 'dart:typed_data' show Uint8List;

import 'package:sqflite/sqflite.dart';

const _kTable = 'project_cache';

Database? _db;
bool _unavailable = false;

Future<Database?> _open() async {
  if (_unavailable) return null;
  final existing = _db;
  if (existing != null) return existing;
  try {
    final dir = await getDatabasesPath();
    final db = await openDatabase(
      '$dir/project_data_cache.db',
      version: 1,
      onCreate: (db, version) => db.execute('''
        CREATE TABLE $_kTable (
          cache_key TEXT PRIMARY KEY,
          lock_version INTEGER NOT NULL,
          schema_version INTEGER NOT NULL,
          meta_gz BLOB,
          low_res_geo_gz BLOB,
          full_geo_gz BLOB,
          full_details_gz BLOB,
          updated_at INTEGER NOT NULL
        )
      '''),
    );
    _db = db;
    return db;
  } catch (_) {
    // No sqflite plugin registered for this runtime (or any other open
    // failure) — stop retrying and behave as a permanent cache miss.
    _unavailable = true;
    return null;
  }
}

Future<void> cacheStoreInit() async {
  await _open();
}

Future<void> cacheStoreClearAll() async {
  try {
    final db = await _open();
    if (db == null) return;
    await db.delete(_kTable);
  } catch (_) {}
}

Uint8List? _gz(Map<String, dynamic>? value) =>
    value == null ? null : Uint8List.fromList(GZipCodec().encode(utf8.encode(jsonEncode(value))));

Map<String, dynamic>? _ungz(Object? blob) {
  if (blob is! List<int> || blob.isEmpty) return null;
  try {
    final decoded = jsonDecode(utf8.decode(GZipCodec().decode(blob)));
    return decoded is Map<String, dynamic> ? decoded : null;
  } catch (_) {
    return null; // corrupt row — treated as a cache miss by the caller
  }
}

Future<Map<String, dynamic>?> cacheStoreRead(String key) async {
  try {
    final db = await _open();
    if (db == null) return null;
    final rows = await db.query(_kTable, where: 'cache_key = ?', whereArgs: [key], limit: 1);
    if (rows.isEmpty) return null;
    final row = rows.first;
    return {
      'lockVersion': row['lock_version'] as int,
      'schemaVersion': row['schema_version'] as int,
      'meta': _ungz(row['meta_gz']),
      'lowResGeo': _ungz(row['low_res_geo_gz']),
      'fullGeo': _ungz(row['full_geo_gz']),
      'fullDetails': _ungz(row['full_details_gz']),
      'updatedAt': row['updated_at'] as int,
    };
  } catch (_) {
    return null;
  }
}

/// Merges [row] into whatever is already stored under [key] — a key present
/// in [row] replaces that column; a key absent from [row] is left as-is. This
/// lets a meta write and a later geo write for the same project each touch
/// only the column they own, without clobbering the other.
Future<void> cacheStoreWrite(String key, Map<String, dynamic> row) async {
  try {
    final db = await _open();
    if (db == null) return;
    final existing = await cacheStoreRead(key);
    final merged = <String, dynamic>{
      'lockVersion': row['lockVersion'] ?? existing?['lockVersion'] ?? 0,
      'schemaVersion': row['schemaVersion'] ?? existing?['schemaVersion'] ?? 0,
      'meta': row.containsKey('meta') ? row['meta'] : existing?['meta'],
      'lowResGeo': row.containsKey('lowResGeo') ? row['lowResGeo'] : existing?['lowResGeo'],
      'fullGeo': row.containsKey('fullGeo') ? row['fullGeo'] : existing?['fullGeo'],
      'fullDetails': row.containsKey('fullDetails') ? row['fullDetails'] : existing?['fullDetails'],
    };
    await db.insert(
      _kTable,
      {
        'cache_key': key,
        'lock_version': merged['lockVersion'],
        'schema_version': merged['schemaVersion'],
        'meta_gz': _gz(merged['meta'] as Map<String, dynamic>?),
        'low_res_geo_gz': _gz(merged['lowResGeo'] as Map<String, dynamic>?),
        'full_geo_gz': _gz(merged['fullGeo'] as Map<String, dynamic>?),
        'full_details_gz': _gz(merged['fullDetails'] as Map<String, dynamic>?),
        'updated_at': DateTime.now().millisecondsSinceEpoch,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  } catch (_) {}
}
