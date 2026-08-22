// Tests for ApiClient/ApiException's handling of non-2xx responses,
// in particular 3xx redirects (self-hosted deployments behind a
// reverse proxy that force http -> https): the Location header should
// surface in the exception message instead of a bare, unhelpful
// "ApiException(308): ".

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:viewtrip_client/src/api/client.dart';

void main() {
  group('ApiClient error handling', () {
    test('a redirect response surfaces the Location header', () async {
      final mock = MockClient((req) async => http.Response(
            '',
            308,
            headers: {'location': 'https://trax.example.com/api/auth/token'},
          ));
      final client = ApiClient(baseUrl: 'http://trax.example.com', httpClient: mock);

      await expectLater(
        client.post('/api/auth/token', {'username': 'a', 'password': 'b'}),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 308)
            .having((e) => e.location, 'location',
                'https://trax.example.com/api/auth/token')),
      );
    });

    test('toString includes the redirect target for 3xx errors', () {
      final e = ApiException(308, '', location: 'https://example.com/x');
      expect(e.toString(), contains('308'));
      expect(e.toString(), contains('https://example.com/x'));
    });

    test('toString falls back to the raw body for non-redirect errors', () {
      final e = ApiException(422, '{"detail":"bad input"}');
      expect(e.toString(), 'ApiException(422): {"detail":"bad input"}');
    });

    test('a normal JSON error response has no location', () async {
      final mock = MockClient((req) async => http.Response('{"detail":"nope"}', 401));
      final client = ApiClient(baseUrl: 'http://trax.example.com', httpClient: mock);

      await expectLater(
        client.get('/api/auth/me'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 401)
            .having((e) => e.location, 'location', isNull)),
      );
    });
  });
}
