/// A byte cache with a total-size budget (issue #276).
///
/// Extracted from `map_panel.dart`'s marker-thumbnail cache, which was a
/// `static final Map<String, Uint8List>` with no eviction at all: on a long
/// trip it accumulated every thumbnail the session ever displayed and
/// released none, which is also why hiding the memories layer freed nothing.
///
/// The same mistake as the server's payload cache in `api/geo.py` — bounding
/// a cache of wildly non-uniform entries by entry *count*, or not at all,
/// when the resource that actually runs out is bytes.
library;

import 'dart:typed_data' show Uint8List;

class BoundedByteCache {
  BoundedByteCache(this.maxBytes) : assert(maxBytes > 0);

  final int maxBytes;

  // Insertion-ordered (Dart's Map guarantees this), so `keys.first` is the
  // least recently *added* entry. Good enough here: entries are
  // interchangeable and cheap to refetch from the on-disk L2.
  final Map<String, Uint8List> _entries = <String, Uint8List>{};
  int _bytes = 0;

  int get bytes => _bytes;
  int get length => _entries.length;

  Uint8List? operator [](String key) => _entries[key];

  bool containsKey(String key) => _entries.containsKey(key);

  /// Stores [value], evicting oldest-first until within [maxBytes].
  ///
  /// A re-put of an existing key replaces it and re-accounts the difference,
  /// rather than double-counting — the bug that would otherwise let the
  /// budget drift upward on every refresh.
  void put(String key, Uint8List value) {
    final existing = _entries.remove(key);
    if (existing != null) _bytes -= existing.length;
    _entries[key] = value;
    _bytes += value.length;
    // Never evict the entry just stored: a single value larger than the whole
    // budget should be held for its caller rather than dropped on the floor,
    // and the next put will retire it.
    while (_bytes > maxBytes && _entries.length > 1) {
      final oldest = _entries.keys.first;
      _bytes -= _entries.remove(oldest)!.length;
    }
  }

  void clear() {
    _entries.clear();
    _bytes = 0;
  }
}
