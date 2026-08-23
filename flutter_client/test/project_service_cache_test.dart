// ProjectService's read-through/write-through wiring to projectDataCache —
// the mechanism that lets switching between view mode and manage mode reuse
// data the other mode already fetched instead of re-downloading it. See
// project_data_cache.dart for the full design.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:viewtrip_client/src/api/client.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/project_data_cache.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

const _ref = ProjectRef(name: 'Trip');

http.Response _json(Map<String, dynamic> body) =>
    http.Response(jsonEncode(body), 200);

void main() {
  setUp(() => projectDataCache.resetForTest());

  test('getDetailsMeta always hits the network, even on a repeat call',
      () async {
    var calls = 0;
    api = ApiClient(
        baseUrl: '',
        httpClient: MockClient((req) async {
          calls++;
          return _json({'lock_version': 1, 'name': 'Trip'});
        }));
    final svc = ProjectService();

    await svc.getDetailsMeta(_ref);
    await svc.getDetailsMeta(_ref);

    expect(calls, 2, reason: 'meta is the freshness oracle — it must never be served from cache');
  });

  test('getGeo is served from cache on a repeat call once meta confirms the '
      'project has not changed', () async {
    var geoCalls = 0;
    api = ApiClient(
        baseUrl: '',
        httpClient: MockClient((req) async {
          if (req.url.path.contains('/geo/')) {
            geoCalls++;
            return _json({'type': 'FeatureCollection', 'features': []});
          }
          return _json({'lock_version': 1, 'name': 'Trip'});
        }));
    final svc = ProjectService();

    await svc.getDetailsMeta(_ref); // establishes lock_version 1
    await svc.getGeo(_ref);
    await svc.getDetailsMeta(_ref); // repeat meta — still lock_version 1
    await svc.getGeo(_ref); // should be served from projectDataCache

    expect(geoCalls, 1);
  });

  test('a lock_version change invalidates the cached geo', () async {
    var geoCalls = 0;
    var version = 1;
    api = ApiClient(
        baseUrl: '',
        httpClient: MockClient((req) async {
          if (req.url.path.contains('/geo/')) {
            geoCalls++;
            return _json({'type': 'FeatureCollection', 'features': []});
          }
          return _json({'lock_version': version, 'name': 'Trip'});
        }));
    final svc = ProjectService();

    await svc.getDetailsMeta(_ref);
    await svc.getGeo(_ref);
    version = 2; // simulates a mutation landing on the server meanwhile
    await svc.getDetailsMeta(_ref);
    await svc.getGeo(_ref);

    expect(geoCalls, 2, reason: 'a changed lock_version must force a re-fetch');
  });

  test('bypassCache always hits the network, cache hit or not', () async {
    var detailsCalls = 0;
    api = ApiClient(
        baseUrl: '',
        httpClient: MockClient((req) async {
          if (req.url.path == '/api/projects/Trip') {
            detailsCalls++;
            return _json({'name': 'Trip', 'activities': []});
          }
          return _json({'lock_version': 1, 'name': 'Trip'});
        }));
    final svc = ProjectService();

    await svc.getDetailsMeta(_ref);
    await svc.getDetails(_ref); // populates the cache
    await svc.getDetails(_ref, bypassCache: true); // must not be served from cache

    expect(detailsCalls, 2);
  });

  test('view mode and manage mode share the same full-details cache slot',
      () async {
    // Regression test for the reported bug: switching from view mode to
    // manage mode (or back) re-downloaded the ~12 MB full-details payload
    // even though the other mode had just fetched it. Both modes go through
    // plain ProjectService.getDetails() — view mode's own fetchFullDetails()
    // writes into the very same projectDataCache slot (see view_screen.dart).
    var detailsCalls = 0;
    api = ApiClient(
        baseUrl: '',
        httpClient: MockClient((req) async {
          if (req.url.path == '/api/projects/Trip') {
            detailsCalls++;
            return _json({'name': 'Trip', 'activities': []});
          }
          return _json({'lock_version': 1, 'name': 'Trip'});
        }));

    await ProjectService().getDetailsMeta(_ref);
    await ProjectService().getDetails(_ref); // e.g. manage mode's background elevation fetch
    await ProjectService().getDetails(_ref); // e.g. view mode's fetchFullDetails, moments later

    expect(detailsCalls, 1);
  });
}
