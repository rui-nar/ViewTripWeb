// Service-layer tests for MembersService (issue #106 — travel companion):
// member list / invite create+revoke / remove, and the invite preview/accept
// endpoints, exercised against an injected MockClient (same approach as
// share_content_generator_test.dart).

import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:viewtrip_client/src/api/client.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/members_service.dart';

void main() {
  group('MembersService', () {
    test('listMembers GETs /members and parses rows owner-first', () async {
      String? path;
      final mock = MockClient((req) async {
        path = '${req.url.path}?${req.url.query}';
        return http.Response(
          jsonEncode({
            'members': [
              {
                'user_id': 1,
                'display_name': 'Alice',
                'avatar_url': '',
                'role': 'owner'
              },
              {
                'user_id': 7,
                'display_name': 'Bob',
                'avatar_url': 'http://x/a.png',
                'role': 'editor'
              },
            ],
          }),
          200,
        );
      });
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      final members =
          await svc.listMembers(const ProjectRef(name: 'My Trip'));

      expect(path, '/api/projects/My%20Trip/members?');
      expect(members, hasLength(2));
      expect(members.first.role, 'owner');
      expect(members.first.isOwner, isTrue);
      expect(members.last.userId, 7);
      expect(members.last.displayName, 'Bob');
      expect(members.last.avatarUrl, 'http://x/a.png');
    });

    test('listMembers appends ?owner= for a shared ref', () async {
      Uri? url;
      final mock = MockClient((req) async {
        url = req.url;
        return http.Response(jsonEncode({'members': []}), 200);
      });
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      await svc.listMembers(
          const ProjectRef(name: 'Trip', ownerId: 3, role: 'editor'));

      expect(url!.path, '/api/projects/Trip/members');
      expect(url!.queryParameters['owner'], '3');
    });

    test('createInvite POSTs and returns the token', () async {
      http.Request? seen;
      final mock = MockClient((req) async {
        seen = req;
        return http.Response(jsonEncode({'token': 'tok123'}), 200);
      });
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      final token = await svc.createInvite(const ProjectRef(name: 'Trip'));

      expect(token, 'tok123');
      expect(seen!.method, 'POST');
      expect(seen!.url.path, '/api/projects/Trip/members/invite');
    });

    test('createInvite surfaces a 409 (E2EE account) as ApiException with '
        'the server detail intact', () async {
      final mock = MockClient((req) async => http.Response(
          jsonEncode({'detail': 'Travel companions are not available'}), 409));
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      expect(
        () => svc.createInvite(const ProjectRef(name: 'Trip')),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 409)
            .having((e) => e.body, 'body', contains('not available'))),
      );
    });

    test('revokeInvite DELETEs the invite', () async {
      http.Request? seen;
      final mock = MockClient((req) async {
        seen = req;
        return http.Response('', 204);
      });
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      await svc.revokeInvite(const ProjectRef(name: 'Trip'));

      expect(seen!.method, 'DELETE');
      expect(seen!.url.path, '/api/projects/Trip/members/invite');
    });

    test('removeMember DELETEs the member row', () async {
      http.Request? seen;
      final mock = MockClient((req) async {
        seen = req;
        return http.Response('', 204);
      });
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      await svc.removeMember(const ProjectRef(name: 'Trip'), 7);

      expect(seen!.method, 'DELETE');
      expect(seen!.url.path, '/api/projects/Trip/members/7');
    });

    test('previewInvite GETs /api/invites/{token} and parses the preview',
        () async {
      Uri? url;
      final mock = MockClient((req) async {
        url = req.url;
        return http.Response(
            jsonEncode({'project_name': 'Alps', 'owner_name': 'Alice'}), 200);
      });
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      final preview = await svc.previewInvite('tok123');

      expect(url!.path, '/api/invites/tok123');
      expect(preview.projectName, 'Alps');
      expect(preview.ownerName, 'Alice');
    });

    test('previewInvite propagates 404 (unknown/revoked token)', () async {
      final mock = MockClient((req) async =>
          http.Response(jsonEncode({'detail': 'Invite not found'}), 404));
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      expect(
        () => svc.previewInvite('nope'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 404)),
      );
    });

    test('acceptInvite POSTs and returns an editor ProjectRef', () async {
      http.Request? seen;
      final mock = MockClient((req) async {
        seen = req;
        return http.Response(jsonEncode({'name': 'Alps', 'owner_id': 3}), 200);
      });
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      final ref = await svc.acceptInvite('tok123');

      expect(seen!.method, 'POST');
      expect(seen!.url.path, '/api/invites/tok123/accept');
      expect(ref, const ProjectRef(name: 'Alps', ownerId: 3, role: 'editor'));
      expect(ref.isEditor, isTrue);
    });

    test('acceptInvite propagates 409 (caller owns the trip)', () async {
      final mock = MockClient((req) async =>
          http.Response(jsonEncode({'detail': 'You already own this trip'}), 409));
      final svc = MembersService(ApiClient(baseUrl: '', httpClient: mock));

      expect(
        () => svc.acceptInvite('tok123'),
        throwsA(isA<ApiException>()
            .having((e) => e.statusCode, 'statusCode', 409)),
      );
    });
  });
}
