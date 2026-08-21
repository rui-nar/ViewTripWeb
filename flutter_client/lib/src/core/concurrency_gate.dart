/// Caps how many async tasks run at once, queuing the rest FIFO.
///
/// Built for `MapPanel`'s memory markers: with one HTTP thumbnail fetch per
/// marker and no virtualization (`flutter_map` builds every marker up
/// front, not just the visible ones), a photo-heavy trip fired 100+
/// concurrent requests the instant its map opened — enough to OOM-kill the
/// production API container repeatedly in one day. This gate bounds that
/// fan-out app-wide for whatever it wraps.
library;

import 'dart:async';
import 'dart:collection';

class ConcurrencyGate {
  ConcurrencyGate(this.maxConcurrent) : assert(maxConcurrent > 0);

  final int maxConcurrent;
  int _active = 0;
  final Queue<Completer<void>> _waiters = Queue<Completer<void>>();

  Future<T> run<T>(Future<T> Function() task) async {
    if (_active >= maxConcurrent) {
      final waiter = Completer<void>();
      _waiters.add(waiter);
      await waiter.future;
    }
    _active++;
    try {
      return await task();
    } finally {
      _active--;
      if (_waiters.isNotEmpty) {
        _waiters.removeFirst().complete();
      }
    }
  }
}
