// Post-import photo polling (startPhotoPolling / _refreshMemoryPhotos) used
// to mutate `items[i]` in place and keep the same List instance. MapPanel's
// marker cache only recomputes on `!identical(items, _lastItems)`, so that
// in-place mutation was invisible to it — a memory that had 0 photos when the
// map first built stayed a black marker forever, no matter how many photos
// the poller found. Fixed by giving `items` a new list identity whenever the
// poller actually changes something.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

const _ref = ProjectRef(name: 'Trip');

Map<String, dynamic> _memoryItem(String id, List<String> photos) => {
      'item_type': 'memory',
      'memory': {'id': id, 'photos': photos},
    };

class _PhotoPollService extends ProjectService {
  _PhotoPollService(this.freshPhotos);
  final List<String> freshPhotos;
  int calls = 0;

  @override
  Future<Map<String, dynamic>> getDetails(ProjectRef ref,
      {bool bypassCache = false}) async {
    calls++;
    return {
      'name': 'Trip',
      'items': [_memoryItem('mem-1', freshPhotos)],
    };
  }
}

void main() {
  test('a photo-count change gives items a new list identity', () async {
    final service = _PhotoPollService(['a', 'b']);
    final notifier = ProjectNotifier(service)
      ..ref = _ref
      ..items = [_memoryItem('mem-1', const [])];
    addTearDown(notifier.dispose);

    final originalItems = notifier.items;

    notifier.startPhotoPolling(_ref,
        interval: const Duration(milliseconds: 1), maxTicks: 1);
    // Let the timer tick and its async body (getDetails + notifyListeners) run.
    await Future.delayed(const Duration(milliseconds: 50));

    expect(service.calls, greaterThanOrEqualTo(1));
    expect(identical(notifier.items, originalItems), isFalse,
        reason: 'a same-object mutation would leave MapPanel\'s '
            'identical(items, _lastItems) cache check blind to the change');
    final mem = notifier.items[0]['memory'] as Map;
    expect(mem['photos'], ['a', 'b']);
  });

  test('no photo-count change leaves items untouched', () async {
    final service = _PhotoPollService(['a']);
    final notifier = ProjectNotifier(service)
      ..ref = _ref
      ..items = [_memoryItem('mem-1', const ['a'])];
    addTearDown(notifier.dispose);

    final originalItems = notifier.items;

    notifier.startPhotoPolling(_ref,
        interval: const Duration(milliseconds: 1), maxTicks: 1);
    await Future.delayed(const Duration(milliseconds: 50));

    expect(identical(notifier.items, originalItems), isTrue);
  });

  test('default poll budget outlives the old 20-tick (60s) cutoff', () async {
    // A large bulk import's slower photo downloads used to outlast the old
    // 60s window (maxTicks: 20 @ 3s) with no further signal once it gave up.
    // Only the interval is overridden here (for test speed) — maxTicks is
    // left at its production default so this proves the widened budget
    // itself, not a test-only value.
    final service = _PhotoPollService(['a']);
    final notifier = ProjectNotifier(service)
      ..ref = _ref
      ..items = [_memoryItem('mem-1', const [])];
    addTearDown(notifier.dispose);

    notifier.startPhotoPolling(_ref, interval: const Duration(milliseconds: 1));
    // The old default would have stopped after 20 ticks; wait well past that
    // (with margin for slow/CI timer granularity) to prove the timer is
    // still polling under the new budget.
    await Future.delayed(const Duration(milliseconds: 250));

    expect(service.calls, greaterThan(20));
  });
}
