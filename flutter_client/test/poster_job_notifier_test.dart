// Tests createPosterJob's job-creation request against a fake HTTP client
// (mirrors polarsteps_token_expiry_test.dart's ApiClient(httpClient:
// MockClient(...)) injection pattern) — happy path (POST returns job_id) and
// an error path (ApiException surfaced without retrying/polling). Issue #14:
// the client no longer polls for job completion, so there is nothing beyond
// job creation left to test here.

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:viewtrip_client/src/api/client.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/poster_job_notifier.dart';

http.Response _json(int status, Object body) => http.Response(
      jsonEncode(body),
      status,
      headers: {'content-type': 'application/json'},
    );

void main() {
  group('createPosterJob', () {
    test('POSTs the request shape to the poster endpoint and returns the '
        'job id', () async {
      Map<String, dynamic>? capturedBody;
      final mock = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.path, '/api/projects/Trip/poster');
        capturedBody = jsonDecode(req.body) as Map<String, dynamic>;
        return _json(201, {'job_id': 42});
      });
      final client = ApiClient(httpClient: mock)..setToken('jwt');

      final jobId = await createPosterJob(
        ref: const ProjectRef(name: 'Trip'),
        bounds: {'north': 1, 'south': 0, 'east': 1, 'west': 0},
        orientation: 'landscape',
        config: {'distance': true},
        memories: const [],
        client: client,
      );

      expect(jobId, 42);
      expect(capturedBody, {
        'bounds': {'north': 1, 'south': 0, 'east': 1, 'west': 0},
        'orientation': 'landscape',
        'config': {'distance': true},
        'memories': [],
      });
    });

    test('a job-creation API error is thrown as ApiException', () async {
      final mock = MockClient((req) async => http.Response('boom', 500));
      final client = ApiClient(httpClient: mock)..setToken('jwt');

      expect(
        () => createPosterJob(
          ref: const ProjectRef(name: 'Trip'),
          bounds: const {},
          orientation: 'landscape',
          config: const {},
          memories: const [],
          client: client,
        ),
        throwsA(isA<ApiException>()),
      );
    });
  });

  group('fetchPosterPreview', () {
    test('POSTs the request shape to the preview endpoint and returns the '
        'raw PNG bytes', () async {
      final pngBytes = [0x89, 0x50, 0x4E, 0x47];
      Map<String, dynamic>? capturedBody;
      final mock = MockClient((req) async {
        expect(req.method, 'POST');
        expect(req.url.path, '/api/projects/Trip/poster/preview');
        capturedBody = jsonDecode(req.body) as Map<String, dynamic>;
        return http.Response.bytes(pngBytes, 200,
            headers: {'content-type': 'image/png'});
      });
      final client = ApiClient(httpClient: mock)..setToken('jwt');

      final preview = await fetchPosterPreview(
        ref: const ProjectRef(name: 'Trip'),
        bounds: {'north': 1, 'south': 0, 'east': 1, 'west': 0},
        orientation: 'landscape',
        config: {'distance': true},
        memories: const [
          {'id': 1, 'lat': 0.5, 'lon': 0.5, 'date': '2024-01-01'}
        ],
        client: client,
      );

      expect(preview.bytes, pngBytes);
      expect(preview.warning, isNull);
      expect(preview.hasWarning, isFalse);
      expect(capturedBody, {
        'bounds': {'north': 1, 'south': 0, 'east': 1, 'west': 0},
        'orientation': 'landscape',
        'config': {'distance': true},
        'memories': [
          {'id': 1, 'lat': 0.5, 'lon': 0.5, 'date': '2024-01-01'}
        ],
      });
    });

    test('a non-2xx response throws ApiException rather than returning bytes',
        () async {
      final mock = MockClient((req) async => http.Response('boom', 500));
      final client = ApiClient(httpClient: mock)..setToken('jwt');

      expect(
        () => fetchPosterPreview(
          ref: const ProjectRef(name: 'Trip'),
          bounds: const {},
          orientation: 'landscape',
          config: const {},
          memories: const [],
          client: client,
        ),
        throwsA(isA<ApiException>()),
      );
    });

    test('surfaces the X-Poster-Warning header when the basemap is missing',
        () async {
      // A degraded preview still returns 200 with a usable PNG; the warning
      // is what tells the user the grey background is a fault, not a design.
      final mock = MockClient((req) async => http.Response.bytes(
            [0x89, 0x50, 0x4E, 0x47],
            200,
            headers: {
              'content-type': 'image/png',
              'x-poster-warning': 'Map imagery unavailable: MAPBOX_TOKEN is not configured',
            },
          ));
      final client = ApiClient(httpClient: mock)..setToken('jwt');

      final preview = await fetchPosterPreview(
        ref: const ProjectRef(name: 'Trip'),
        bounds: const {},
        orientation: 'landscape',
        config: const {},
        memories: const [],
        client: client,
      );

      expect(preview.hasWarning, isTrue);
      expect(preview.warning, contains('MAPBOX_TOKEN'));
      expect(preview.bytes, isNotEmpty, reason: 'preview still renders');
    });

    test('an empty warning header is not treated as a warning', () async {
      final mock = MockClient((req) async => http.Response.bytes(
            [0x89, 0x50, 0x4E, 0x47], 200,
            headers: {'content-type': 'image/png', 'x-poster-warning': ''},
          ));
      final client = ApiClient(httpClient: mock)..setToken('jwt');

      final preview = await fetchPosterPreview(
        ref: const ProjectRef(name: 'Trip'),
        bounds: const {},
        orientation: 'landscape',
        config: const {},
        memories: const [],
        client: client,
      );

      expect(preview.hasWarning, isFalse);
    });
  });
}
