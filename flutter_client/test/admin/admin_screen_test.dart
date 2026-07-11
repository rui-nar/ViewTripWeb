import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:viewtrip_client/src/admin/admin_screen.dart';
import 'package:viewtrip_client/src/admin/admin_service.dart';
import 'package:viewtrip_client/src/core/design_tokens.dart';

class _FakeAdminService extends AdminService {
  List<Map<String, dynamic>> searchResult = [];
  int? resetCalledFor;
  int? adminToggledFor;
  bool? adminToggledTo;
  Object? setAdminError;

  @override
  Future<Map<String, dynamic>> getStats() async => {
        'totals': {
          'users': 3,
          'projects': 5,
          'activities': 40,
          'memories': 12,
          'storage_bytes': 2 * 1024 * 1024,
          'recent_signups_7d': 1,
        },
        'users': [
          {
            'id': 1, 'email': 'a@x.com', 'display_name': 'Alice',
            'auth_provider': 'local', 'created_at': 1700000000,
            'project_count': 2, 'activity_count': 10, 'memory_count': 3,
            'storage_bytes': 1024, 'encryption_tier': 'high',
          },
        ],
      };

  @override
  Future<void> refreshStorage() async {}

  @override
  Future<List<Map<String, dynamic>>> searchUsers(String q, {int limit = 50}) async =>
      searchResult;

  @override
  Future<String> resetPassword(int userInfoId) async {
    resetCalledFor = userInfoId;
    return 'TEMP-PW-123';
  }

  @override
  Future<void> setAdmin(int userInfoId, bool isAdmin) async {
    if (setAdminError != null) throw setAdminError!;
    adminToggledFor = userInfoId;
    adminToggledTo = isAdmin;
  }
}

Future<void> _pump(WidgetTester tester, Widget child) async {
  tester.view.physicalSize = const Size(1100, 1600);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);
  await tester.pumpWidget(MaterialApp(home: child));
  await tester.pumpAndSettle();
}

void main() {
  group('pure helpers', () {
    test('humanizeBytes', () {
      expect(humanizeBytes(512), '512 B');
      expect(humanizeBytes(1024), '1.0 KB');
      expect(humanizeBytes(2 * 1024 * 1024), '2.0 MB');
    });
    test('formatSignup', () {
      expect(formatSignup(0), '—');
      expect(formatSignup(1700000000), '2023-11-14');
    });
    test('tierColor maps tiers', () {
      expect(tierColor('high'), kSuccess);
      expect(tierColor('medium'), kWarning);
      expect(tierColor('none'), kColorOther);
    });
  });

  testWidgets('renders totals + a per-user row with its encryption tier',
      (tester) async {
    await _pump(tester, AdminScreen(service: _FakeAdminService()));
    expect(find.text('Users'), findsWidgets);
    expect(find.text('3'), findsWidgets); // user total
    expect(find.text('Alice'), findsOneWidget);
    expect(find.text('high'), findsWidgets); // tier chip
  });

  testWidgets('reset is enabled for None/Low, disabled for Medium/High',
      (tester) async {
    final svc = _FakeAdminService()
      ..searchResult = [
        {'id': 10, 'email': 'low@x.com', 'display_name': 'Low', 'encryption_tier': 'low'},
        {'id': 11, 'email': 'hi@x.com', 'display_name': 'Hi', 'encryption_tier': 'high'},
      ];
    await _pump(tester, AdminScreen(service: svc));

    await tester.enterText(find.byType(TextField), 'x');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    final buttons = tester
        .widgetList<OutlinedButton>(find.widgetWithText(OutlinedButton, 'Reset password'))
        .toList();
    expect(buttons, hasLength(2));
    expect(buttons[0].onPressed, isNotNull); // low → enabled
    expect(buttons[1].onPressed, isNull); // high → disabled

    await tester.tap(find.widgetWithText(OutlinedButton, 'Reset password').first);
    await tester.pumpAndSettle();
    expect(svc.resetCalledFor, 10);
    expect(find.text('TEMP-PW-123'), findsOneWidget); // temp-password dialog
  });

  testWidgets('admin toggle grants and revokes, label flips after the call',
      (tester) async {
    final svc = _FakeAdminService()
      ..searchResult = [
        {'id': 20, 'email': 'plain@x.com', 'display_name': 'Plain', 'encryption_tier': 'none', 'is_admin': false},
      ];
    await _pump(tester, AdminScreen(service: svc));

    await tester.enterText(find.byType(TextField), 'plain');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    expect(find.widgetWithText(OutlinedButton, 'Make admin'), findsOneWidget);
    await tester.tap(find.widgetWithText(OutlinedButton, 'Make admin'));
    await tester.pumpAndSettle();

    expect(svc.adminToggledFor, 20);
    expect(svc.adminToggledTo, true);
    expect(find.widgetWithText(OutlinedButton, 'Remove admin'), findsOneWidget);
  });

  testWidgets('admin toggle failure (e.g. self-revoke 409) surfaces a snackbar',
      (tester) async {
    final svc = _FakeAdminService()
      ..setAdminError = Exception('You cannot remove your own admin access.')
      ..searchResult = [
        {'id': 21, 'email': 'me@x.com', 'display_name': 'Me', 'encryption_tier': 'none', 'is_admin': true},
      ];
    await _pump(tester, AdminScreen(service: svc));

    await tester.enterText(find.byType(TextField), 'me');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    await tester.tap(find.widgetWithText(OutlinedButton, 'Remove admin'));
    await tester.pumpAndSettle();

    expect(find.text('You cannot remove your own admin access.'), findsOneWidget);
    // Label stays as-is since the call failed.
    expect(find.widgetWithText(OutlinedButton, 'Remove admin'), findsOneWidget);
  });

  testWidgets('search row stays readable (no per-character wrap) on a narrow width',
      (tester) async {
    final svc = _FakeAdminService()
      ..searchResult = [
        {
          'id': 30, 'email': 'narrow@x.com', 'display_name': 'Narrow Name',
          'encryption_tier': 'none', 'is_admin': false,
        },
      ];
    // Narrow enough to force the stacked (non-Row) layout branch, but not so
    // narrow that the (pre-existing, unrelated) _SectionCard header overflows.
    tester.view.physicalSize = const Size(560, 900);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(MaterialApp(home: AdminScreen(service: svc)));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'narrow');
    await tester.testTextInput.receiveAction(TextInputAction.done);
    await tester.pumpAndSettle();

    expect(tester.takeException(), isNull); // no RenderFlex overflow
    // The full name renders as one Text widget, not split per character.
    expect(find.text('Narrow Name'), findsOneWidget);
  });
}
