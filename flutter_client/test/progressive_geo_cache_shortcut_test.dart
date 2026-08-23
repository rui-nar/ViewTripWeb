// Regression test for the Android view/manage mode-toggle ANR.
//
// _loadFullGeoProgressively() used to unconditionally replay its batched
// low-res→full-res reveal (up to ~8 full map rebuilds, 80ms apart — see
// progressiveGeoBatchSize) on every load(), even when the full-res geo was
// already sitting in projectDataCache from the mode just left. Toggling
// between view and manage mode re-ran that batched replay every single time,
// even though nothing was actually "progressively arriving" — the data was
// already complete in memory. On a large trip, several seconds of
// back-to-back full-map rebuilds was enough to trip Android's ANR watchdog,
// and it reappeared after dismissal because the batch sequence just kept
// going.
//
// The fix: when projectDataCache already has full geo for the ref, apply it
// in one shot instead of replaying the batch simulation. This test asserts
// getGeo() (the only path that drives the batched reveal) is never called
// when the cache is already warm.

import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_data_cache.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

const _ref = ProjectRef(name: 'Trip');

Map<String, dynamic> _details() => {
      'name': 'Trip',
      'lock_version': 1,
      'activities': [
        {'id': 111, 'name': 'Ride', 'type': 'Ride'},
      ],
      'items': [
        {'item_type': 'activity', 'activity_id': 111},
      ],
    };

Map<String, dynamic> _fullGeo() => {
      'type': 'FeatureCollection',
      'features': [
        {
          'type': 'Feature',
          'properties': {'activity_id': '111'},
          'geometry': {
            'type': 'LineString',
            'coordinates': [
              [1.0, 2.0],
              [1.1, 2.1],
            ],
          },
        },
      ],
    };

class _CountingService extends ProjectService {
  int getGeoCalls = 0;

  @override
  Future<Map<String, dynamic>> getDetailsMeta(ProjectRef ref) async =>
      {'lock_version': 1, 'name': 'Trip'};

  @override
  Future<Map<String, dynamic>> getLowResGeo(ProjectRef ref) async =>
      {'type': 'FeatureCollection', 'features': <dynamic>[]};

  @override
  Future<Map<String, dynamic>> getDetails(ProjectRef ref, {bool bypassCache = false}) async =>
      _details();

  @override
  Future<Map<String, dynamic>> getGeo(ProjectRef ref, {bool bypassCache = false}) async {
    getGeoCalls++;
    return _fullGeo();
  }
}

void main() {
  setUp(() => projectDataCache.resetForTest());

  test(
      'a mode toggle with a warm full-geo cache applies it in one shot '
      'instead of replaying the batched network-reveal path', () async {
    // Seed the cache exactly as the mode just left would have: a live /meta
    // establishing lock_version 1, then a full geo fetch.
    projectDataCache.onMetaFetched(_ref, {'lock_version': 1, 'name': 'Trip'});
    projectDataCache.writeFullGeo(_ref, _fullGeo());

    final service = _CountingService();
    final notifier = ProjectNotifier(service);

    await notifier.load(_ref);
    // _loadFullGeoProgressively runs unawaited in the background; give it a
    // moment to finish. The batched path needs 80ms per repaint, so a short
    // wait here would still catch it if the shortcut regressed.
    await Future<void>.delayed(const Duration(milliseconds: 30));

    expect(service.getGeoCalls, 0,
        reason: 'a warm cache must never fall through to the batched '
            'network-reveal path (that path is the only caller of getGeo())');
    expect(notifier.isGeoLoaded, isTrue);
    expect(notifier.geo?['features'], hasLength(1));
    expect((notifier.geo?['features'] as List).first['properties']['activity_id'], '111');
  });
}
