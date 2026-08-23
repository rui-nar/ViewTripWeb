/// No-op on-device cache backend — used on web (and any platform without
/// `dart:io`), where there is no local filesystem to persist thumbnail bytes
/// to. Marker thumbnails still work there; they just never survive past the
/// current tab's lifetime (in-memory only), same as ProjectDataCache's own
/// web behavior.
library;

import 'dart:typed_data' show Uint8List;

Future<void> photoCacheStoreInit() async {}

Future<void> photoCacheStoreClearAll() async {}

Future<Uint8List?> photoCacheStoreRead(String key) async => null;

Future<void> photoCacheStoreWrite(String key, Uint8List bytes) async {}
