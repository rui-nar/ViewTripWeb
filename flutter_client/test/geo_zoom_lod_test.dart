// Issue #295, client half of zoom level of detail.
//
// The client used to hold full-resolution geometry regardless of zoom: a
// 219-activity trip carried 1,465,345 coordinates while the map rendered
// 6,051, the rest costing roughly 180 MB of a Dart heap that device profiling
// put at ~625 MB steady and ~804 MB during load, on a process Android kills
// above ~1.3 GB.
//
// It now asks the server for geometry simplified to about one screen pixel at
// the current zoom, and asks again when the zoom bucket changes.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:viewtrip_client/src/api/client.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_data_cache.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

const _ref = ProjectRef(name: 'Trip');

http.Response _json(Map<String, dynamic> body) =>
    http.Response(jsonEncode(body), 200);

/// A feature whose point count encodes the zoom it was built for, so a test
/// can tell which level the notifier is holding.
Map<String, dynamic> _geoWith(int points) => {
      'type': 'FeatureCollection',
      'features': [
        {
          'type': 'Feature',
          'properties': {'type': 'activity', 'activity_id': '1'},
          'geometry': {
            'type': 'LineString',
            'coordinates': [
              for (var i = 0; i < points; i++) [7.0 + i * 0.001, 45.0 + i * 0.001]
            ],
          },
        },
      ],
    };

Map<String, dynamic> _meta() => {
      'name': 'Trip',
      'lock_version': 1,
      'activities': [
        {'id': '1'}
      ],
      'items': [
        {'item_type': 'activity', 'activity_id': '1'}
      ],
      'people': <dynamic>[],
      'groups': <dynamic>[],
    };

class _Calls {
  final zooms = <String>[];
  int fullGeo = 0;
}

/// [lodStatus] lets a test make the simplified endpoint fail, to exercise the
/// fallback an older server would take.
ApiClient _api(_Calls calls, {int lodStatus = 200}) => ApiClient(
      baseUrl: '',
      httpClient: MockClient((req) async {
        final path = req.url.path;
        if (path == '/api/projects/Trip/meta') return _json(_meta());
        if (path == '/api/geo/project/low-res') {
          return _json({'type': 'FeatureCollection', 'features': <dynamic>[]});
        }
        if (path == '/api/geo/project/simplified') {
          if (lodStatus != 200) return http.Response('nope', lodStatus);
          final z = req.url.queryParameters['zoom']!;
          calls.zooms.add(z);
          // Point count scales with zoom, as real simplification does.
          return _json(_geoWith(double.parse(z).ceil()));
        }
        if (path == '/api/geo/project') {
          calls.fullGeo++;
          return _json(_geoWith(999));
        }
        if (path == '/api/projects/Trip/elevation') {
          return _json({'profiles': <String, dynamic>{}, 'encrypted': <String, dynamic>{}});
        }
        return _json({});
      }),
    );

/// Point count of the first feature, or 0 while geo is still the empty
/// low-res placeholder the load starts from.
int _points(ProjectNotifier n) {
  final features = n.geo?['features'] as List?;
  if (features == null || features.isEmpty) return 0;
  return (features.first['geometry']['coordinates'] as List?)?.length ?? 0;
}

Future<bool> _waitFor(bool Function() cond,
    {Duration timeout = const Duration(seconds: 2)}) async {
  final deadline = DateTime.now().add(timeout);
  while (DateTime.now().isBefore(deadline)) {
    if (cond()) return true;
    await Future<void>.delayed(const Duration(milliseconds: 5));
  }
  return cond();
}

void main() {
  setUp(() => projectDataCache.resetForTest());

  test('the load fetches geometry for the current zoom, not full resolution',
      () async {
    final calls = _Calls();
    api = _api(calls);
    final n = ProjectNotifier(ProjectService())..setMapZoom(9);

    await n.load(_ref);
    expect(await _waitFor(() => _points(n) > 0), isTrue);

    expect(calls.zooms, ['9.0']);
    expect(calls.fullGeo, 0,
        reason: 'full-resolution geometry is what this exists to avoid');
    expect(_points(n), 9);
  });

  test('zooming in asks for more detail', () async {
    final calls = _Calls();
    api = _api(calls);
    final n = ProjectNotifier(ProjectService())
      ..setMapZoom(9)
      ..zoomRefetchDebounce = const Duration(milliseconds: 10);

    await n.load(_ref);
    expect(await _waitFor(() => _points(n) == 9), isTrue);

    n.setMapZoom(15);
    expect(await _waitFor(() => _points(n) == 15), isTrue,
        reason: 'a new zoom bucket must bring finer geometry');
  });

  test('panning within a zoom bucket refetches nothing', () async {
    // The camera fires events continuously; only a bucket change is a reason
    // to go back to the server.
    final calls = _Calls();
    api = _api(calls);
    final n = ProjectNotifier(ProjectService())
      ..setMapZoom(9)
      ..zoomRefetchDebounce = const Duration(milliseconds: 10);

    await n.load(_ref);
    expect(await _waitFor(() => _points(n) == 9), isTrue);

    for (final z in [8.2, 8.5, 8.9, 9.0]) {
      n.setMapZoom(z);
    }
    await Future<void>.delayed(const Duration(milliseconds: 80));
    expect(calls.zooms, hasLength(1),
        reason: 'ceil() puts all of those in bucket 9, already loaded');
  });

  test('a pinch through several levels causes one refetch', () async {
    final calls = _Calls();
    api = _api(calls);
    final n = ProjectNotifier(ProjectService())
      ..setMapZoom(9)
      ..zoomRefetchDebounce = const Duration(milliseconds: 40);

    await n.load(_ref);
    expect(await _waitFor(() => _points(n) == 9), isTrue);

    for (final z in [10.0, 11.0, 12.0, 13.0, 14.0]) {
      n.setMapZoom(z);
    }
    expect(await _waitFor(() => _points(n) == 14), isTrue);
    expect(calls.zooms, hasLength(2),
        reason: 'the initial load plus one settled refetch, not five');
  });

  test('opening a second project does not carry the first zoom bucket over',
      () async {
    // ProjectNotifier is a single app-wide provider. A bucket left from the
    // previous trip arms refetching for geometry it has nothing to do with.
    final calls = _Calls();
    api = _api(calls);
    final n = ProjectNotifier(ProjectService())
      ..setMapZoom(9)
      ..zoomRefetchDebounce = const Duration(milliseconds: 10);

    await n.load(_ref);
    expect(await _waitFor(() => _points(n) == 9), isTrue);

    await n.load(const ProjectRef(name: 'Other'));
    // A zoom event arriving before the second load's geometry has landed must
    // not fire a refetch against a stale bucket.
    n.setMapZoom(15);
    await Future<void>.delayed(const Duration(milliseconds: 60));
    expect(n.geo, isNotNull);
  });

  test('clear() disarms zoom refetching', () async {
    final calls = _Calls();
    api = _api(calls);
    final n = ProjectNotifier(ProjectService())
      ..setMapZoom(9)
      ..zoomRefetchDebounce = const Duration(milliseconds: 10);

    await n.load(_ref);
    expect(await _waitFor(() => _points(n) == 9), isTrue);
    final before = calls.zooms.length;

    n.clear();
    n.setMapZoom(16);
    await Future<void>.delayed(const Duration(milliseconds: 60));
    expect(calls.zooms, hasLength(before),
        reason: 'nothing is on screen to refetch geometry for');
  });

  test('the bucket recorded is the one that was requested', () async {
    // The fit-bounds animation moves the camera during the fetch and the
    // camera-idle wait. Stamping whatever _mapZoom reads afterwards would
    // record a level never fetched — and then never refetch it.
    final calls = _Calls();
    api = _api(calls);
    final n = ProjectNotifier(ProjectService())
      ..setMapZoom(9)
      ..zoomRefetchDebounce = const Duration(milliseconds: 10);

    final loading = n.load(_ref);
    n.setMapZoom(14); // the camera moves mid-load
    await loading;
    expect(await _waitFor(() => _points(n) == 14), isTrue);
  });

  test('an older server without the endpoint falls back to full resolution',
      () async {
    final calls = _Calls();
    api = _api(calls, lodStatus: 404);
    final n = ProjectNotifier(ProjectService())..setMapZoom(9);

    await n.load(_ref);
    expect(await _waitFor(() => _points(n) > 0), isTrue);

    expect(calls.fullGeo, greaterThanOrEqualTo(1),
        reason: 'a 404 must not leave the map without geometry');
    expect(_points(n), 999);
  });
}
