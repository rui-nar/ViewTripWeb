// Tests PosterJobNotifier's polling logic against a fake HTTP client (mirrors
// polarsteps_token_expiry_test.dart's ApiClient(httpClient: MockClient(...))
// injection pattern) — happy path (pending -> running -> done, download path
// available) and a failure path (status becomes 'failed', error_message
// surfaced), plus a creation-error and a poll-timeout case.

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

PosterJobNotifier _notifier(
  Future<http.Response> Function(http.Request) handler, {
  int maxPollAttempts = 10,
}) {
  final mock = MockClient((req) => handler(req));
  final client = ApiClient(httpClient: mock)..setToken('jwt');
  return PosterJobNotifier(
    ref: const ProjectRef(name: 'Trip'),
    client: client,
    pollInterval: Duration.zero,
    maxPollAttempts: maxPollAttempts,
  );
}

void main() {
  group('PosterJobNotifier', () {
    test('happy path: pending -> running -> done exposes the download path',
        () async {
      var pollCount = 0;
      final n = _notifier((req) async {
        if (req.method == 'POST' &&
            req.url.path == '/api/projects/Trip/poster') {
          return _json(201, {'job_id': 42});
        }
        if (req.method == 'GET' &&
            req.url.path == '/api/projects/Trip/poster/42') {
          pollCount++;
          if (pollCount == 1) {
            return _json(200, {'status': 'pending', 'stage': null});
          }
          if (pollCount == 2) {
            return _json(200, {'status': 'running', 'stage': 'Rendering'});
          }
          return _json(200, {'status': 'done', 'stage': null});
        }
        return _json(404, {'detail': 'unexpected ${req.url.path}'});
      });

      var notifyCount = 0;
      n.addListener(() => notifyCount++);

      await n.start(
        bounds: {'north': 1, 'south': 0, 'east': 1, 'west': 0},
        orientation: 'landscape',
        config: {'distance': true},
        memories: const [],
      );

      expect(n.jobId, 42);
      expect(n.status, 'done');
      expect(n.isDone, isTrue);
      expect(n.isBusy, isFalse);
      expect(n.isFailed, isFalse);
      expect(n.error, isNull);
      expect(pollCount, 3);
      expect(n.downloadPath('png'),
          '/api/projects/Trip/poster/42/download?format=png');
      expect(n.downloadPath('pdf'),
          '/api/projects/Trip/poster/42/download?format=pdf');
      expect(notifyCount, greaterThan(0));
    });

    test('failure path: a failed status surfaces error_message', () async {
      final n = _notifier((req) async {
        if (req.method == 'POST') return _json(201, {'job_id': 7});
        return _json(200, {
          'status': 'failed',
          'stage': null,
          'error_message': 'Renderer crashed',
        });
      });

      await n.start(
        bounds: {'north': 1, 'south': 0, 'east': 1, 'west': 0},
        orientation: 'portrait',
        config: const {},
        memories: const [],
      );

      expect(n.jobId, 7);
      expect(n.status, 'failed');
      expect(n.isFailed, isTrue);
      expect(n.isDone, isFalse);
      expect(n.error, 'Renderer crashed');
    });

    test('a job-creation API error is surfaced without ever polling',
        () async {
      var getCalls = 0;
      final n = _notifier((req) async {
        if (req.method == 'GET') getCalls++;
        return http.Response('boom', 500);
      });

      await n.start(
        bounds: const {},
        orientation: 'landscape',
        config: const {},
        memories: const [],
      );

      expect(n.status, 'failed');
      expect(n.jobId, isNull);
      expect(n.error, 'boom');
      expect(getCalls, 0);
    });

    test('exhausting maxPollAttempts without a terminal status times out '
        'as a failure', () async {
      final n = _notifier(
        (req) async {
          if (req.method == 'POST') return _json(201, {'job_id': 1});
          return _json(200, {'status': 'running', 'stage': 'Still working'});
        },
        maxPollAttempts: 3,
      );

      await n.start(
        bounds: const {},
        orientation: 'landscape',
        config: const {},
        memories: const [],
      );

      expect(n.status, 'failed');
      expect(n.error, contains('timed out'));
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

      final bytes = await fetchPosterPreview(
        ref: const ProjectRef(name: 'Trip'),
        bounds: {'north': 1, 'south': 0, 'east': 1, 'west': 0},
        orientation: 'landscape',
        config: {'distance': true},
        memories: const [
          {'id': 1, 'lat': 0.5, 'lon': 0.5, 'date': '2024-01-01'}
        ],
        client: client,
      );

      expect(bytes, pngBytes);
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
  });
}
