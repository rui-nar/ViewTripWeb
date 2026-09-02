// Issue #292 — the heavy project payloads must not be decoded on the UI
// isolate. See docs/PERF_MAP_LOAD.md.
//
// The load-bearing test here is `main isolate stays responsive`: it starts a
// 1 ms periodic timer and counts its ticks while a large geo payload is
// decoded. Dart's periodic timers do NOT catch up on ticks missed while the
// event loop is blocked — they simply reschedule — so a synchronous decode
// yields a handful of ticks no matter how long it took, while an off-isolate
// decode yields hundreds. That gap is what makes the assertion robust despite
// being wall-clock based.

import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:viewtrip_client/src/api/client.dart';
import 'package:viewtrip_client/src/core/perf_timing.dart' show kFrameBudgetMs;
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/map/polyline_decoder.dart';
import 'package:viewtrip_client/src/projects/heavy_decode.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';

/// Google-encoded-polyline encoder — the inverse of [decodePolyline], needed
/// only to build a realistically large fixture. The round-trip is asserted in
/// `fixture sanity` below so a silently wrong fixture can't make the real
/// assertions vacuous.
String encodePolyline(List<(double lat, double lon)> points) {
  final buf = StringBuffer();
  var prevLat = 0, prevLon = 0;
  void writeValue(int delta) {
    var v = delta < 0 ? ~(delta << 1) : (delta << 1);
    while (v >= 0x20) {
      buf.writeCharCode((0x20 | (v & 0x1f)) + 63);
      v >>= 5;
    }
    buf.writeCharCode(v + 63);
  }

  for (final (lat, lon) in points) {
    final iLat = (lat * 1e5).round();
    final iLon = (lon * 1e5).round();
    writeValue(iLat - prevLat);
    writeValue(iLon - prevLon);
    prevLat = iLat;
    prevLon = iLon;
  }
  return buf.toString();
}

/// A geo FeatureCollection with [activities] encoded-polyline activity
/// features of [pointsPer] points each — shaped like what
/// `/api/geo/project?encoded=1` actually returns.
Map<String, dynamic> buildEncodedGeo({
  required int activities,
  required int pointsPer,
}) {
  final features = <Map<String, dynamic>>[];
  for (var a = 0; a < activities; a++) {
    final pts = <(double, double)>[];
    for (var i = 0; i < pointsPer; i++) {
      // A wandering track — consecutive-delta encoding, like real GPS.
      pts.add((45.0 + a * 0.01 + i * 0.00001, 7.0 + a * 0.01 + i * 0.00002));
    }
    features.add({
      'type': 'Feature',
      'properties': {'activity_id': 'a$a', 'polyline': encodePolyline(pts)},
      'geometry': {'type': 'LineString', 'coordinates': <dynamic>[]},
    });
  }
  return {'type': 'FeatureCollection', 'features': features};
}

Uint8List jsonBytes(Object o) =>
    Uint8List.fromList(utf8.encode(jsonEncode(o)));

/// Runs [body] while counting 1 ms timer ticks, so a caller can tell whether
/// the event loop kept running. Returns the tick count and the wall time.
Future<({int ticks, int elapsedMs, T value})> withHeartbeat<T>(
    Future<T> Function() body) async {
  var ticks = 0;
  final timer = Timer.periodic(const Duration(milliseconds: 1), (_) => ticks++);
  final sw = Stopwatch()..start();
  try {
    final value = await body();
    return (ticks: ticks, elapsedMs: sw.elapsedMilliseconds, value: value);
  } finally {
    timer.cancel();
  }
}

void main() {
  // 100 activities x 5000 points: ~500k coordinates, the scale of a long trip
  // and comfortably over kInlineDecodeThresholdBytes.
  late Uint8List bigGeoBytes;
  // How long the OLD inline path would block for. Measured once, directly,
  // rather than inferred from the async path's wall time — the async path
  // includes isolate spawn, so using it to judge whether the fixture is big
  // enough conflates the thing being measured with the measurement.
  late int inlineDecodeMs;

  setUpAll(() {
    bigGeoBytes = jsonBytes(buildEncodedGeo(activities: 100, pointsPer: 5000));
    final sw = Stopwatch()..start();
    decodeGeoBytes(bigGeoBytes);
    inlineDecodeMs = sw.elapsedMilliseconds;
  });

  group('fixture sanity', () {
    test('encodePolyline round-trips through decodePolyline', () {
      final pts = [(45.0, 7.0), (45.001, 7.002), (44.999, 7.004)];
      final decoded = decodePolyline(encodePolyline(pts));
      expect(decoded, hasLength(3));
      for (var i = 0; i < pts.length; i++) {
        expect(decoded[i].lat, closeTo(pts[i].$1, 1e-5));
        expect(decoded[i].lon, closeTo(pts[i].$2, 1e-5));
      }
    });

    test('the large fixture really is over the inline-decode threshold', () {
      expect(bigGeoBytes.length, greaterThan(kInlineDecodeThresholdBytes));
    });

    test('decoding the fixture inline would blow several frame budgets', () {
      // Without this the responsiveness assertions below could pass vacuously
      // on a fixture that got cheap enough to decode between two timer ticks.
      expect(inlineDecodeMs, greaterThan(3 * kFrameBudgetMs),
          reason: 'fixture no longer represents a large trip; grow it');
    });
  });

  group('decodeGeoBytes', () {
    test('expands encoded polylines into GeoJSON coordinates', () async {
      final geo = buildEncodedGeo(activities: 2, pointsPer: 3);
      final out = decodeGeoBytes(jsonBytes(geo));
      final coords =
          (out['features'] as List).first['geometry']['coordinates'] as List;
      expect(coords, hasLength(3));
      // GeoJSON is [lon, lat] — the order this app has crashed on before.
      expect((coords.first as List)[0], closeTo(7.0, 1e-4));
      expect((coords.first as List)[1], closeTo(45.0, 1e-4));
    });

    test('matches the old two-step inline path exactly', () {
      final geo = buildEncodedGeo(activities: 3, pointsPer: 50);
      final bytes = jsonBytes(geo);
      // What ApiClient._handle + ProjectService.getGeo used to do.
      final legacy =
          expandEncodedActivities(jsonDecode(utf8.decode(bytes)) as Map<String, dynamic>);
      expect(decodeGeoBytes(bytes), legacy);
    });

    test('leaves already-expanded features alone', () {
      final geo = {
        'type': 'FeatureCollection',
        'features': [
          {
            'type': 'Feature',
            'properties': {'activity_id': 'a', 'polyline': 'ignored'},
            'geometry': {
              'type': 'LineString',
              'coordinates': [
                [7.0, 45.0],
                [7.1, 45.1],
              ],
            },
          },
        ],
      };
      final out = decodeGeoBytes(jsonBytes(geo));
      expect((out['features'] as List).first['geometry']['coordinates'],
          hasLength(2));
    });
  });

  group('off-isolate decoding', () {
    test('small and large payloads produce identical results', () async {
      final small = buildEncodedGeo(activities: 1, pointsPer: 4);
      final smallBytes = jsonBytes(small);
      expect(smallBytes.length, lessThan(kInlineDecodeThresholdBytes));

      // Below the threshold this decodes inline, above it on a worker. The
      // path taken must never change the answer.
      expect(await decodeGeoOffIsolate(smallBytes), decodeGeoBytes(smallBytes));

      // The large payload is checked structurally rather than by deep
      // equality: matcher equality over a 500k-point tree takes minutes and
      // proves nothing extra — decodeGeoBytes is the same function on both
      // sides of the threshold, so what needs pinning is that the isolate hop
      // returns it intact.
      final viaIsolate = await decodeGeoOffIsolate(bigGeoBytes);
      final features = viaIsolate['features'] as List;
      expect(features, hasLength(100));
      final first = features.first['geometry']['coordinates'] as List;
      final last = features.last['geometry']['coordinates'] as List;
      expect(first, hasLength(5000));
      expect(last, hasLength(5000));
      expect(first.first, decodeGeoBytes(bigGeoBytes)['features'][0]
          ['geometry']['coordinates'][0]);
    });

    test('decodeJsonMapOffIsolate round-trips a plain map', () async {
      expect(await decodeJsonMapOffIsolate(jsonBytes({'a': 1})), {'a': 1});
    });

    test('the main isolate stays responsive while a large geo payload decodes',
        () async {
      final r = await withHeartbeat(() => decodeGeoOffIsolate(bigGeoBytes));

      // A blocked event loop yields a handful of ticks regardless of duration
      // (periodic timers do not catch up). An unblocked one ticks ~once per ms.
      // Fixture adequacy is pinned separately by the inlineDecodeMs test above.
      expect(r.ticks, greaterThan(r.elapsedMs ~/ 4),
          reason: 'event loop was starved — the decode ran on the UI isolate');
    });
  });

  group('ApiClient.getBytes', () {
    test('returns the undecoded response body', () async {
      final client = ApiClient(
        baseUrl: '',
        httpClient: MockClient((_) async => http.Response('{"a":1}', 200)),
      );
      expect(await client.getBytes('/x'), utf8.encode('{"a":1}'));
    });

    test('throws ApiException carrying the error body', () async {
      final client = ApiClient(
        baseUrl: '',
        httpClient: MockClient((_) async => http.Response('nope', 404)),
      );
      await expectLater(
        client.getBytes('/x'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 404)
            .having((e) => e.body, 'body', 'nope')),
      );
    });
  });

  group('ProjectService.getGeo', () {
    test('decodes a large trip without blocking the main isolate', () async {
      final previous = api;
      api = ApiClient(
        baseUrl: '',
        httpClient: MockClient((_) async => http.Response.bytes(bigGeoBytes, 200)),
      );
      addTearDown(() => api = previous);

      final svc = ProjectService();
      final r = await withHeartbeat(
          () => svc.getGeo(const ProjectRef(name: 'Big Trip'), bypassCache: true));

      // The payload really was expanded on the way through.
      final coords =
          (r.value['features'] as List).first['geometry']['coordinates'] as List;
      expect(coords, hasLength(5000));

      expect(r.ticks, greaterThan(r.elapsedMs ~/ 4),
          reason: 'event loop was starved — the decode ran on the UI isolate');
    });
  });
}
