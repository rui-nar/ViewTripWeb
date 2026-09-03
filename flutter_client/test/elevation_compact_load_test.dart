// Issue #295. The elevation upgrade fetches the compact /elevation endpoint
// instead of the full details payload — 33 MB on a 180-day trip, ~9 s to
// fetch and ~5 s to decode, of which elevation was the only part this load
// needed.
//
// These pin the behaviour the camera-idle test cannot: it mocks both routes,
// so it passes whichever path is taken. Here the details route *counts its
// calls*, which is the only way to prove which one actually ran.

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

/// encode_profile_pairs([[0.0, 100.0], [1.0, 110.0]])
const _encoded = r'?o}@o}@gE';

http.Response _json(Map<String, dynamic> body) =>
    http.Response(jsonEncode(body), 200);

Map<String, dynamic> _geo() => {
      'type': 'FeatureCollection',
      'features': [
        {
          'type': 'Feature',
          'properties': {'type': 'activity', 'activity_id': '1'},
          'geometry': {
            'type': 'LineString',
            'coordinates': [
              [7.0, 45.0],
              [7.01, 45.01],
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

/// Counts details calls so a test can tell which path ran.
class _Counts {
  int details = 0;
  int elevation = 0;
}

ApiClient _api(_Counts counts, {required http.Response Function() elevation}) =>
    ApiClient(
      baseUrl: '',
      httpClient: MockClient((req) async {
        final path = req.url.path;
        if (path == '/api/projects/Trip/meta') return _json(_meta());
        if (path == '/api/geo/project/low-res') {
          return _json({'type': 'FeatureCollection', 'features': <dynamic>[]});
        }
        if (path == '/api/geo/project') return _json(_geo());
        if (path == '/api/projects/Trip/elevation') {
          counts.elevation++;
          return elevation();
        }
        if (path == '/api/projects/Trip') {
          counts.details++;
          return _json({
            'name': 'Trip',
            'activities': [
              {
                'id': '1',
                'elevation_profile': [
                  [0.0, 100],
                  [1.0, 110]
                ],
              }
            ],
            'items': [
              {'item_type': 'activity', 'activity_id': '1'}
            ],
            'people': <dynamic>[],
            'groups': <dynamic>[],
          });
        }
        return _json({});
      }),
    );

Future<void> _settle(ProjectNotifier n) async {
  for (var i = 0; i < 60 && n.fullTrack.isEmpty; i++) {
    await Future<void>.delayed(const Duration(milliseconds: 10));
  }
}

void main() {
  setUp(() => projectDataCache.resetForTest());

  test('the compact endpoint supplies elevation, and details is never fetched',
      () async {
    final counts = _Counts();
    api = _api(counts,
        elevation: () => _json({
              'profiles': {'1': _encoded},
              'encrypted': <String, dynamic>{},
            }));
    final n = ProjectNotifier(ProjectService());
    await n.load(_ref);
    await _settle(n);

    expect(n.fullTrack, isNotEmpty, reason: 'elevation must have landed');
    expect(counts.elevation, 1);
    expect(counts.details, 0,
        reason: 'the 33 MB payload must not be fetched for elevation alone');
  });

  test('an older server without the endpoint falls back to details', () async {
    final counts = _Counts();
    api = _api(counts, elevation: () => http.Response('Not Found', 404));
    final n = ProjectNotifier(ProjectService());
    await n.load(_ref);
    await _settle(n);

    expect(n.fullTrack, isNotEmpty);
    expect(counts.details, 1, reason: 'a 404 must not lose the elevation data');
  });

  test('encrypted profiles fall back to details', () async {
    // The endpoint cannot open an E2EE envelope; decrypting is the details
    // payload's job, so their presence means this path cannot serve the trip.
    final counts = _Counts();
    api = _api(counts,
        elevation: () => _json({
              'profiles': <String, dynamic>{},
              'encrypted': {'1': 'v1:opaque'},
            }));
    final n = ProjectNotifier(ProjectService());
    await n.load(_ref);
    await _settle(n);

    expect(counts.details, 1);
  });

  test('a trip with genuinely no elevation does not fetch details', () async {
    // Empty profiles is a legitimate answer — GPX and manual entries have no
    // elevation — and must not be mistaken for an endpoint failure.
    final counts = _Counts();
    api = _api(counts,
        elevation: () => _json({
              'profiles': <String, dynamic>{},
              'encrypted': <String, dynamic>{},
            }));
    final n = ProjectNotifier(ProjectService());
    await n.load(_ref);
    await Future<void>.delayed(const Duration(milliseconds: 200));

    expect(counts.details, 0);
  });

  test('the decoded profile reaches the activity it belongs to', () async {
    final counts = _Counts();
    api = _api(counts,
        elevation: () => _json({
              'profiles': {'1': _encoded},
              'encrypted': <String, dynamic>{},
            }));
    final n = ProjectNotifier(ProjectService());
    await n.load(_ref);
    await _settle(n);

    final profile = n.activities.first['elevation_profile'] as List;
    expect(profile, hasLength(2));
    expect((profile.last as List)[1], closeTo(110.0, 0.051));
  });
}
