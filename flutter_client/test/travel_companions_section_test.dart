// Widget tests for the "Travel companions" settings section (issue #106):
// role gating (owner sees remove + invite controls, editor sees a read-only
// list plus Leave trip), the invite create → copy URL → revoke block, the
// inline 409 (E2EE) message, and the remove/leave confirm flows. Services are
// mocked by subclassing, like projects_screen_shared_test.dart.

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:viewtrip_client/src/api/client.dart';
import 'package:viewtrip_client/src/auth/auth_notifier.dart';
import 'package:viewtrip_client/src/auth/auth_service.dart';
import 'package:viewtrip_client/src/core/project_ref.dart';
import 'package:viewtrip_client/src/projects/members_service.dart';
import 'package:viewtrip_client/src/projects/project_notifier.dart';
import 'package:viewtrip_client/src/projects/project_service.dart';
import 'package:viewtrip_client/src/projects/travel_companions_section.dart';

class _FakeMembersService extends MembersService {
  List<ProjectMember> members;
  ApiException? createError;
  final removedIds = <int>[];
  int revokeCalls = 0;

  _FakeMembersService(this.members);

  @override
  Future<List<ProjectMember>> listMembers(ProjectRef ref) async => members;

  @override
  Future<String> createInvite(ProjectRef ref) async {
    final err = createError;
    if (err != null) throw err;
    return 'tok123';
  }

  @override
  Future<void> revokeInvite(ProjectRef ref) async {
    revokeCalls++;
  }

  @override
  Future<void> removeMember(ProjectRef ref, int userId) async {
    removedIds.add(userId);
  }
}

AuthNotifier _loggedInAuth(String userId) {
  final auth = AuthNotifier(AuthService());
  auth.updateUser({
    'id': userId,
    'email': 'a@x.com',
    'display_name': 'A',
    'auth_provider': 'local',
  });
  return auth;
}

const _owner = ProjectMember(
    userId: 1, displayName: 'Alice', avatarUrl: '', role: 'owner');
const _editor = ProjectMember(
    userId: 7, displayName: 'Bob', avatarUrl: '', role: 'editor');

ProjectNotifier _notifierWith(_FakeMembersService svc, ProjectRef ref) {
  final notifier = ProjectNotifier(ProjectService(), membersService: svc);
  notifier.ref = ref;
  return notifier;
}

Widget _harness({
  required ProjectNotifier notifier,
  required String authUserId,
}) =>
    MaterialApp(
      home: Scaffold(
        body: MultiProvider(
          providers: [
            ChangeNotifierProvider<AuthNotifier>.value(
                value: _loggedInAuth(authUserId)),
            ChangeNotifierProvider<ProjectNotifier>.value(value: notifier),
          ],
          child: const SingleChildScrollView(child: TravelCompanionsSection()),
        ),
      ),
    );

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  testWidgets('owner sees members, a remove button on non-owner rows only, '
      'and the invite-link block — no Leave trip', (tester) async {
    final svc = _FakeMembersService([_owner, _editor]);
    final notifier = _notifierWith(svc, const ProjectRef(name: 'Trip'));

    await tester.pumpWidget(_harness(notifier: notifier, authUserId: '1'));
    await tester.pump(); // post-frame loadMembers
    await tester.pump();

    expect(find.text('Alice (you)'), findsOneWidget);
    expect(find.text('Bob'), findsOneWidget);
    // Exactly one remove button — for Bob, not for the owner row.
    expect(find.byIcon(Icons.person_remove_outlined), findsOneWidget);
    expect(find.text('Create invite link'), findsOneWidget);
    expect(find.text('Leave trip'), findsNothing);
  });

  testWidgets('owner: Create invite link shows the /join URL with copy and '
      'Revoke; Revoke returns to the create button', (tester) async {
    final svc = _FakeMembersService([_owner, _editor]);
    final notifier = _notifierWith(svc, const ProjectRef(name: 'Trip'));

    await tester.pumpWidget(_harness(notifier: notifier, authUserId: '1'));
    await tester.pump();
    await tester.pump();

    await tester.tap(find.text('Create invite link'));
    await tester.pumpAndSettle();

    expect(find.textContaining('/join/tok123'), findsOneWidget);
    expect(find.byIcon(Icons.content_copy), findsOneWidget);
    expect(find.text('Revoke'), findsOneWidget);

    await tester.tap(find.text('Revoke'));
    await tester.pumpAndSettle();

    expect(svc.revokeCalls, 1);
    expect(find.textContaining('/join/tok123'), findsNothing);
    expect(find.text('Create invite link'), findsOneWidget);
  });

  testWidgets('owner: a 409 from invite creation (E2EE account) surfaces the '
      "server's message inline, without a dialog", (tester) async {
    final svc = _FakeMembersService([_owner])
      ..createError = ApiException(
          409, '{"detail": "Travel companions are not available on encrypted accounts"}');
    final notifier = _notifierWith(svc, const ProjectRef(name: 'Trip'));

    await tester.pumpWidget(_harness(notifier: notifier, authUserId: '1'));
    await tester.pump();
    await tester.pump();

    await tester.tap(find.text('Create invite link'));
    await tester.pumpAndSettle();

    expect(find.textContaining('encrypted accounts'), findsOneWidget);
    expect(find.byType(AlertDialog), findsNothing);
    // Still no invite URL, and the create button remains available.
    expect(find.textContaining('/join/'), findsNothing);
    expect(find.text('Create invite link'), findsOneWidget);
  });

  testWidgets('owner: removing a member asks for confirmation, then removes '
      'the row and calls the service', (tester) async {
    final svc = _FakeMembersService([_owner, _editor]);
    final notifier = _notifierWith(svc, const ProjectRef(name: 'Trip'));

    await tester.pumpWidget(_harness(notifier: notifier, authUserId: '1'));
    await tester.pump();
    await tester.pump();

    await tester.tap(find.byIcon(Icons.person_remove_outlined));
    await tester.pumpAndSettle();
    expect(find.text('Remove companion?'), findsOneWidget);

    await tester.tap(find.widgetWithText(ElevatedButton, 'Remove'));
    await tester.pumpAndSettle();

    expect(svc.removedIds, [7]);
    expect(find.text('Bob'), findsNothing);
  });

  testWidgets('editor sees a read-only member list and Leave trip — no '
      'remove buttons, no invite block', (tester) async {
    final svc = _FakeMembersService([_owner, _editor]);
    final notifier = _notifierWith(
        svc, const ProjectRef(name: 'Trip', ownerId: 1, role: 'editor'));

    await tester.pumpWidget(_harness(notifier: notifier, authUserId: '7'));
    await tester.pump();
    await tester.pump();

    expect(find.text('Alice'), findsOneWidget);
    expect(find.text('Bob (you)'), findsOneWidget);
    expect(find.byIcon(Icons.person_remove_outlined), findsNothing);
    expect(find.text('Create invite link'), findsNothing);
    expect(find.text('Leave trip'), findsOneWidget);
  });

  testWidgets('editor: Leave trip confirms, deletes own membership and '
      'navigates to the projects list', (tester) async {
    final svc = _FakeMembersService([_owner, _editor]);
    final notifier = _notifierWith(
        svc, const ProjectRef(name: 'Trip', ownerId: 1, role: 'editor'));

    final router = GoRouter(
      initialLocation: '/settings',
      routes: [
        GoRoute(
          path: '/settings',
          builder: (context, state) => Scaffold(
            body: SingleChildScrollView(child: TravelCompanionsSection()),
          ),
        ),
        GoRoute(
          path: '/projects',
          builder: (context, state) =>
              const Scaffold(body: Text('PROJECTS LIST')),
        ),
      ],
    );

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthNotifier>.value(value: _loggedInAuth('7')),
          ChangeNotifierProvider<ProjectNotifier>.value(value: notifier),
        ],
        child: MaterialApp.router(routerConfig: router),
      ),
    );
    await tester.pump();
    await tester.pump();

    await tester.tap(find.text('Leave trip'));
    await tester.pumpAndSettle();
    expect(find.text('Leave trip?'), findsOneWidget);

    await tester.tap(find.widgetWithText(ElevatedButton, 'Leave'));
    await tester.pumpAndSettle();

    expect(svc.removedIds, [7]);
    expect(find.text('PROJECTS LIST'), findsOneWidget);
  });
}
