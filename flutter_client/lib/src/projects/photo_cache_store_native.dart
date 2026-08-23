/// sqflite-backed on-device cache for memory-photo thumbnail bytes — the L2
/// layer under `_MarkerThumbImage`'s in-memory L1, so a marker thumbnail
/// already fetched on this device survives an app restart instead of being
/// refetched from scratch on every cold start. Compiled in only via
/// `photo_thumb_cache.dart`'s conditional import (`if (dart.library.io)`);
/// never reachable from web.
///
/// Thumbnail bytes never change once generated, so unlike ProjectDataCache
/// there's no freshness/lock_version to track here — a cache hit is always
/// valid. Every public function here is best-effort: any failure to open or
/// use the database degrades to "nothing was cached" rather than throwing.
library;

import 'dart:typed_data' show Uint8List;

import 'package:sqflite/sqflite.dart';

const _kTable = 'photo_thumb_cache';

Database? _db;
bool _unavailable = false;

Future<Database?> _open() async {
  if (_unavailable) return null;
  final existing = _db;
  if (existing != null) return existing;
  try {
    final dir = await getDatabasesPath();
    final db = await openDatabase(
      '$dir/photo_thumb_cache.db',
      version: 1,
      onCreate: (db, version) => db.execute('''
        CREATE TABLE $_kTable (
          cache_key TEXT PRIMARY KEY,
          bytes BLOB NOT NULL,
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

Future<void> photoCacheStoreInit() async {
  await _open();
}

Future<void> photoCacheStoreClearAll() async {
  try {
    final db = await _open();
    if (db == null) return;
    await db.delete(_kTable);
  } catch (_) {}
}

Future<Uint8List?> photoCacheStoreRead(String key) async {
  try {
    final db = await _open();
    if (db == null) return null;
    final rows = await db.query(_kTable, where: 'cache_key = ?', whereArgs: [key], limit: 1);
    if (rows.isEmpty) return null;
    final bytes = rows.first['bytes'];
    return bytes is List<int> ? Uint8List.fromList(bytes) : null;
  } catch (_) {
    return null;
  }
}

Future<void> photoCacheStoreWrite(String key, Uint8List bytes) async {
  try {
    final db = await _open();
    if (db == null) return;
    await db.insert(
      _kTable,
      {
        'cache_key': key,
        'bytes': bytes,
        'updated_at': DateTime.now().millisecondsSinceEpoch,
      },
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  } catch (_) {}
}
