/// On-device persistence for memory-photo thumbnail bytes — the missing
/// layer under map_panel.dart's `_MarkerThumbImage`. Its in-memory `_cache`
/// (added by #230, the marker-thumbnail-storm fix) only dedupes fetches
/// *within one running app process*; a cold start (closing/reopening the
/// app, or a page reload on web) starts that Map empty again, so every
/// marker refetched from scratch on every app open. This adds an
/// sqflite-backed L2 underneath it on native platforms, mirroring
/// `ProjectDataCache`'s two-layer shape (web has no filesystem — see the
/// conditional import below — and keeps the same session-only behavior it
/// already had).
///
/// Thumbnail bytes never change once generated, so unlike `ProjectDataCache`
/// there's no freshness/lock_version to track: a cache hit is always valid.
/// A deleted photo's entry simply becomes unreachable dead space, reclaimed
/// the same way as everything else via `clearAll()`.
library;

import 'dart:typed_data' show Uint8List;

import 'photo_cache_store_stub.dart'
    if (dart.library.io) 'photo_cache_store_native.dart' as store;

class PhotoThumbCache {
  PhotoThumbCache._();

  Future<void> init() => store.photoCacheStoreInit();

  Future<void> clearAll() => store.photoCacheStoreClearAll();

  Future<Uint8List?> read(String key) => store.photoCacheStoreRead(key);

  /// Fire-and-forget: disk persistence must never add latency to the marker
  /// paint the caller is blocking on.
  void write(String key, Uint8List bytes) {
    store.photoCacheStoreWrite(key, bytes);
  }
}

final PhotoThumbCache photoThumbCache = PhotoThumbCache._();
