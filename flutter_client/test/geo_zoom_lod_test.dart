// Issue #295, client half of zoom level of detail.
//
// The client used to hold full-resolution geometry regardless of zoom: a
// 219-activity trip carried 1,465,345 coordinates while the map rendered
// 6,051, the rest costing roughly 180 MB of a Dart heap that device profiling
// put at ~625 MB steady and ~804 MB during load, on a process Android kills
// above ~1.3 GB.
//
// It now asks the server for geometry simplified to about one screen pixel at
// the current zoom, and asks again when the zoom bucket changes — and, since
// issue #324, scoped to the camera's box, asking again when the camera leaves
// it.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:viewtrip_client/src/api/client.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/geo_viewport.dart';
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
  /// The `bbox` parameter of each simplified request, null when none was sent.
  final boxes = <String?>[];
  int fullGeo = 0;
  bool failLod = false;
}

/// A camera box over the Alps, small enough that a tile-snapped fetch box
/// around it is nowhere near the far-away one the pan tests move to.
const _vp = GeoBox(7.30, 45.30, 7.50, 45.50);

/// [lodStatus] lets a test make the simplified endpoint fail, to exercise the
/// fallback an older server would take; [lodDelay] holds the response so a
/// test can watch what is on screen while a refetch is in flight.
ApiClient _api(_Calls calls,
        {int lodStatus = 200, Duration lodDelay = Duration.zero}) =>
    ApiClient(
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
          calls.boxes.add(req.url.queryParameters['bbox']);
          if (calls.failLod) return http.Response('nope', 500);
          if (lodDelay > Duration.zero) await Future<void>.delayed(lodDelay);
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

  // ── Viewport bounding box (issue #324) ───────────────────────────────────
  //
  // Zoom bounds the DETAIL of the geometry, not its EXTENT, so a deep zoom
  // still fetched — and made the server simplify — the whole trip: measured
  // at 4.0 s per request for a 219-activity trip at zoom 15 against 0.26 s at
  // zoom 9. The camera's box is now sent too, and leaving it is a reason to
  // refetch exactly as changing level is.

  group('viewport scoping', () {
    test('the initial load sends no box', () async {
      // The notifier has no camera box until the map emits its first event,
      // and the whole-trip answer is what fit-to-bounds and the whole-trip
      // elevation cursor are built from. This falls out rather than being a
      // special case, and it is asserted so it stays that way.
      final calls = _Calls();
      api = _api(calls);
      final n = ProjectNotifier(ProjectService())..setMapZoom(9);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) > 0), isTrue);
      expect(calls.boxes, [null]);
    });

    test('a zoom change carries the box the camera is looking at', () async {
      final calls = _Calls();
      api = _api(calls);
      final n = ProjectNotifier(ProjectService())
        ..setMapZoom(9, viewport: _vp)
        ..zoomRefetchDebounce = const Duration(milliseconds: 10);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) == 9), isTrue);

      n.setMapZoom(15, viewport: _vp);
      expect(await _waitFor(() => _points(n) == 15), isTrue);
      expect(calls.boxes.last, isNotNull);
      // Snapped, not raw: an unsnapped box means a server cache entry per pan
      // pixel, and this project has already OOM-killed its API container once
      // with a payload cache bounded by the wrong thing.
      expect(calls.boxes.last, fetchBoxFor(_vp, 15).param);
    });

    test('panning inside the fetched box refetches nothing', () async {
      final calls = _Calls();
      api = _api(calls);
      final n = ProjectNotifier(ProjectService())
        ..setMapZoom(9, viewport: _vp)
        ..zoomRefetchDebounce = const Duration(milliseconds: 10);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) == 9), isTrue);
      n.setMapZoom(15, viewport: _vp);
      expect(await _waitFor(() => _points(n) == 15), isTrue);
      final before = calls.zooms.length;

      // A nudge of a thousandth of a degree, many times, as a real drag does.
      for (var i = 1; i <= 10; i++) {
        n.setMapZoom(15,
            viewport: GeoBox(_vp.west + i * 0.0001, _vp.south + i * 0.0001,
                _vp.east + i * 0.0001, _vp.north + i * 0.0001));
      }
      await Future<void>.delayed(const Duration(milliseconds: 60));
      expect(calls.zooms, hasLength(before),
          reason: 'the box is padded and tile-snapped precisely so a small '
              'pan costs nothing');
    });

    test('panning OUT of the fetched box refetches, at the same zoom', () async {
      // The trigger the zoom bucket alone could never provide: the level has
      // not changed, but the geometry on hand describes somewhere else.
      final calls = _Calls();
      api = _api(calls);
      final n = ProjectNotifier(ProjectService())
        ..setMapZoom(9, viewport: _vp)
        ..zoomRefetchDebounce = const Duration(milliseconds: 10);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) == 9), isTrue);
      n.setMapZoom(15, viewport: _vp);
      expect(await _waitFor(() => calls.boxes.length == 2), isTrue);
      final firstBox = calls.boxes.last;

      n.setMapZoom(15, viewport: const GeoBox(20.0, 50.0, 20.2, 50.2));
      expect(await _waitFor(() => calls.boxes.length == 3), isTrue,
          reason: 'a pan to another region must fetch that region');
      expect(calls.boxes.last, isNot(firstBox));
      expect(calls.zooms.last, '15.0',
          reason: 'same level, different extent');
    });

    test('the map is never blanked while a refetch is in flight', () async {
      // Never blank the map: whatever is drawn stays drawn until new geometry
      // actually lands.
      final calls = _Calls();
      api = _api(calls, lodDelay: const Duration(milliseconds: 120));
      final n = ProjectNotifier(ProjectService())
        ..setMapZoom(9, viewport: _vp)
        ..zoomRefetchDebounce = const Duration(milliseconds: 10);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) == 9), isTrue);

      n.setMapZoom(15, viewport: _vp);
      for (var i = 0; i < 8; i++) {
        await Future<void>.delayed(const Duration(milliseconds: 10));
        expect(_points(n), greaterThan(0),
            reason: 'the previous geometry must stay on screen');
      }
      expect(await _waitFor(() => _points(n) == 15), isTrue);
    });

    test('a failed boxed refetch keeps what is already drawn', () async {
      final calls = _Calls();
      api = _api(calls);
      final n = ProjectNotifier(ProjectService())
        ..setMapZoom(9, viewport: _vp)
        ..zoomRefetchDebounce = const Duration(milliseconds: 10);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) == 9), isTrue);

      calls.failLod = true;
      n.setMapZoom(15, viewport: _vp);
      await Future<void>.delayed(const Duration(milliseconds: 80));
      expect(_points(n), 9, reason: 'slightly wrong detail, never a blank map');
    });

    test('a camera box does not survive into the next project', () async {
      // ProjectNotifier is a single app-wide provider; a box left from the
      // previous trip describes a region this one may be nowhere near.
      final calls = _Calls();
      api = _api(calls);
      final n = ProjectNotifier(ProjectService())
        ..setMapZoom(9, viewport: _vp)
        ..zoomRefetchDebounce = const Duration(milliseconds: 10);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) == 9), isTrue);
      n.setMapZoom(15, viewport: _vp);
      expect(await _waitFor(() => calls.boxes.length == 2), isTrue);

      calls.boxes.clear();
      await n.load(const ProjectRef(name: 'Other'));
      expect(await _waitFor(() => calls.boxes.isNotEmpty), isTrue);
      expect(calls.boxes.first, isNull,
          reason: 'the second load must ask for the whole of ITS trip');
    });

    test('a camera with no usable box asks for the whole trip', () async {
      // An antimeridian-crossing or not-yet-laid-out camera. Null means "ask
      // for everything", which is what the code did before the box existed.
      final calls = _Calls();
      api = _api(calls);
      final n = ProjectNotifier(ProjectService())
        ..setMapZoom(9, viewport: _vp)
        ..zoomRefetchDebounce = const Duration(milliseconds: 10);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) == 9), isTrue);
      // viewportBox() returns null for a crossing box, so nothing is passed.
      n.setMapZoom(15, viewport: viewportBox(179.0, 45.0, -179.0, 46.0));
      expect(await _waitFor(() => calls.boxes.length == 2), isTrue);
      expect(calls.boxes.last, isNull);
    });

    test('whole-trip zoom asks for a box that covers the world', () async {
      // At a zoom that shows everything the box degenerates to the trip
      // bounds. That has to fall out of the arithmetic, not need a mode.
      final calls = _Calls();
      api = _api(calls);
      final n = ProjectNotifier(ProjectService())
        ..setMapZoom(9, viewport: _vp)
        ..zoomRefetchDebounce = const Duration(milliseconds: 10);

      await n.load(_ref);
      expect(await _waitFor(() => _points(n) == 9), isTrue);

      n.setMapZoom(2, viewport: const GeoBox(-170, -80, 170, 80));
      expect(await _waitFor(() => calls.boxes.length == 2), isTrue);
      final box = fetchBoxFor(const GeoBox(-170, -80, 170, 80), 2);
      expect(calls.boxes.last, box.param);
      expect(box.west, -180.0);
      expect(box.east, 180.0);
    });
  });
}
