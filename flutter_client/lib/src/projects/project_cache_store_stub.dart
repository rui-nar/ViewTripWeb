/// No-op on-device cache backend — used on web (and any platform without
/// `dart:io`), where there is no local filesystem to persist a project cache
/// to. `ProjectDataCache` still works there; it just never survives past the
/// current tab's lifetime (in-memory only).
library;

Future<void> cacheStoreInit() async {}

Future<void> cacheStoreClearAll() async {}

Future<Map<String, dynamic>?> cacheStoreRead(String key) async => null;

Future<void> cacheStoreWrite(String key, Map<String, dynamic> row) async {}
